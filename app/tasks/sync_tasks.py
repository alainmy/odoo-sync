"""
Celery tasks for synchronization operations between WooCommerce and Odoo.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from celery import Task
from sqlalchemy.orm import Session
from app.celery_app import celery_app
from app.core.config import settings
from app.crud.odoo import OdooClient
from app.models.product_models import OdooProduct
from app.services.woocommerce import (
    woocommerce_type_to_odoo_type,
    odoo_product_to_woocommerce,
    create_or_update_woocommerce_product,
)
from app.services.product_variants import (
    has_variants,
    validate_attributes_synced,
    build_wc_attributes_for_product,
    sync_product_variations_sync
)
from app.db.session import SessionLocal
from app.tasks.task_logger import log_celery_task_with_retry
from app.tasks.task_monitoring import update_task_progress
from app.tasks.sync_helpers import create_wc_api_client
from app.services.woocommerce import get_wc_api_from_instance_config, \
    build_category_chain, category_for_export
from app.services.woocommerce.shipping import (
    normalize_odoo_carrier,
    get_active_shipping_zone_id,
    create_or_update_woocommerce_shipping_method
)
from app.models.shipping_method_sync import ShippingMethodSync
from app.repositories import ShippingMethodRepository
from app.models.admin import CategorySync, ProductSync, ProductVariantSync, WooCommerceInstance
from app.models.tax_sync import TaxSync
from app.utils.image_helper import ImageHelper
from app.models.user_model import ClientSync
from app.repositories.client_sync_repository import ClientSyncRepository
from app.services.odoo_service import create_customer_in_odoo
from app.services.woocommerce.client import wc_request_with_logging
from app.crud.odoo_order import OrderClient


logger = logging.getLogger(__name__)


# ==================== Helper Functions ====================

def _normalize_odoo_many2one_field(key: str, value: List, normalized_data: Dict, odoo_config: Dict) -> None:
    """Normaliza campos many2one de Odoo"""
    if key == 'categ_id' and len(value) == 2:
        normalized_data['categ_id'] = value[0] if isinstance(
            value[0], int) else None
        normalized_data['categ_name'] = value[1] if len(value) > 1 else None
        logger.debug(
            f"Extracted category: ID={normalized_data['categ_id']}, Name={normalized_data['categ_name']}")
    elif key == 'product_tag_ids' and value:
        normalized_data[key] = _fetch_and_normalize_tags(value, odoo_config)
    elif len(value) == 2 and isinstance(value[0], int):
        normalized_data[key] = value[0]
    else:
        normalized_data[key] = value


def _fetch_and_normalize_tags(tag_ids: List, odoo_config: Dict) -> List[Dict]:
    """Consulta y normaliza tags desde Odoo"""
    if not tag_ids:
        return []

    if isinstance(tag_ids[0], int):
        logger.debug(f"Fetching tag names from Odoo for IDs: {tag_ids}")
        try:
            odoo_client = OdooClient(
                odoo_config["url"],
                odoo_config["db"],
                odoo_config["username"],
                odoo_config["password"]
            )
            tags_data = odoo_client.search_read_sync(
                'product.tag',
                [['id', 'in', tag_ids]],
                ['id', 'name']
            )
            return [
                {
                    "id": tag.get('id'),
                    "name": tag.get('name', ''),
                    "ks_woo_id": None
                }
                for tag in tags_data
            ]
        except Exception as e:
            logger.error(f"Error fetching tags from Odoo: {e}", exc_info=True)
            return []
    elif isinstance(tag_ids[0], list):
        return [
            {
                "id": tag[0] if isinstance(tag, list) and len(tag) > 0 else tag,
                "name": tag[1] if isinstance(tag, list) and len(tag) > 1 else "",
                "ks_woo_id": None
            }
            for tag in tag_ids
        ]
    return []


def normalize_odoo_product_data(odoo_product_data: Dict[str, Any], odoo_config: Dict) -> Dict[str, Any]:
    """
    Normaliza datos de producto de Odoo.
    Convierte False a None, procesa many2one, many2many, etc.
    """
    normalized_data = {}

    for key, value in odoo_product_data.items():
        if value is False:
            normalized_data[key] = None
        elif isinstance(value, list):
            _normalize_odoo_many2one_field(
                key, value, normalized_data, odoo_config)
        else:
            normalized_data[key] = value

    return normalized_data


def create_wc_api_client(wc_config: Dict[str, str]):
    """Crea cliente WooCommerce API desde configuración"""
    if not wc_config:
        return None

    from woocommerce import API
    return API(
        url=wc_config["url"],
        consumer_key=wc_config["consumer_key"],
        consumer_secret=wc_config["consumer_secret"],
        wp_api=True,
        version="wc/v3",
        timeout=60,
        verify_ssl=False
    )


def prepare_variable_product_data(
    normalized_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str],
    db: Session
) -> Tuple[bool, Optional[List[Dict]], Optional[Dict]]:
    """
    Valida y prepara datos para producto variable.

    Returns:
        (is_variable, product_attributes, error_dict or None)
    """
    if not has_variants(normalized_data):
        return False, None, None

    logger.info(f"Product has variants, validating attributes...")

    # Initialize Odoo client
    odoo_client = OdooClient(
        url=odoo_config["url"],
        db=odoo_config["db"],
        username=odoo_config["username"],
        password=odoo_config["password"]
    )

    # Validate attributes
    attribute_line_ids = normalized_data.get('attribute_line_ids', [])
    validation = validate_attributes_synced(
        attribute_line_ids=attribute_line_ids,
        instance_id=instance_id,
        db=db,
        odoo_client=odoo_client
    )

    if not validation["valid"]:
        error_msg = f"Cannot sync variable product: {len(validation['missing_attributes'])} attributes not synced"
        logger.error(error_msg)
        logger.error(f"Missing attributes: {validation['missing_attributes']}")
        logger.error(f"Missing values: {validation['missing_values']}")

        return False, None, {
            "message": error_msg,
            "missing_attributes": validation['missing_attributes'],
            "missing_values": validation['missing_values']
        }

    # Build attributes
    product_attributes = build_wc_attributes_for_product(
        attribute_line_ids=attribute_line_ids,
        instance_id=instance_id,
        db=db,
        odoo_client=odoo_client
    )

    logger.info(
        f"Product configured as variable with {len(product_attributes)} attributes")
    return True, product_attributes, None


def sync_product_variations(
    odoo_product_id: int,
    wc_product_id: int,
    odoo_client,
    db: Session,
    wcapi,
    instance_id: int
) -> Dict[str, Any]:
    """
    Sincroniza variantes de un producto variable.

    Returns:
        Dict con resultado de sincronización de variantes
    """
    logger.info(f"Syncing variations for variable product {wc_product_id}...")

    try:
        variation_result = sync_product_variations_sync(
            odoo_client=odoo_client,
            template_id=odoo_product_id,
            wc_parent_id=wc_product_id,
            db=db,
            wcapi=wcapi,
            instance_id=instance_id
        )

        if not variation_result.get('success', False):
            logger.warning(
                f"Some variations failed: {variation_result.get('failed', 0)}/{variation_result.get('total_variations', 0)}"
            )
        else:
            logger.info(
                f"All {variation_result.get('synced', 0)} variations synced successfully")

        return variation_result

    except Exception as e:
        logger.error(f"Error syncing variations: {e}", exc_info=True)
        return {
            "success": False,
            "total_variations": 0,
            "synced": 0,
            "failed": 0,
            "errors": [str(e)]
        }


# ==================== Helpers for Order Sync ====================

def _sync_partner_with_database(
    odoo_id: int,
    woo_id: int,
    email: str,
    name: str,
    contact_type: str,
    db: Session,
    client_sync_repo: 'ClientSyncRepository',
    parent_id: Optional[int] = None
) -> ClientSync:
    """
    Create or update a partner sync record in the database.

    Args:
        odoo_id: Odoo partner ID
        woo_id: WooCommerce customer ID
        email: Partner email
        name: Partner name
        contact_type: Type of contact (contact, billing, shipping)
        db: Database session
        client_sync_repo: ClientSyncRepository instance
        parent_id: Parent partner ID for hierarchical relationships

    Returns:
        The created or updated ClientSync record
    """
    existing_sync = db.query(ClientSync).filter(
        ClientSync.odoo_id == odoo_id,
        ClientSync.contact_type == contact_type
    ).first()

    if existing_sync:
        # Update existing record
        sync_record = client_sync_repo.update_sync_record(
            existing_sync,
            woo_id=woo_id,
            email=email,
            name=name,
            sync_status="synced"
        )
        logger.info(
            f"Updated sync record: type={contact_type}, odoo_id={odoo_id}")
    else:
        # Create new record
        sync_record = client_sync_repo.create_sync_record(
            odoo_id=odoo_id,
            woo_id=woo_id,
            email=email,
            name=name,
            contact_type=contact_type,
            sync_status="synced",
            parent_id=parent_id
        )
        logger.info(
            f"Created sync record: type={contact_type}, odoo_id={odoo_id}")

    return sync_record


def _handle_sync_partner(
    model: str,
    domain: List,
    partner_name: str,
    partner_data: Dict[str, Any],
    contact_type: str,
    woocommerce_id: int,
    customer_email: str,
    odoo_client: OdooClient,
    db: Session,
    client_sync_repo: 'ClientSyncRepository',
    parent_sync: Optional[ClientSync] = None,
    create_func=None
) -> int:
    """
    Handle the complete flow of finding/creating/updating a partner and its sync record.

    Args:
        model: Odoo model (res.partner)
        domain: Search domain for existing partner
        partner_name: Name for logging
        partner_data: Data to send to Odoo
        contact_type: Type of contact (contact, billing, shipping)
        woocommerce_id: WooCommerce customer ID
        customer_email: Customer email
        odoo_client: OdooClient instance
        db: Database session
        client_sync_repo: ClientSyncRepository instance
        parent_sync: Parent sync record (for hierarchical relationships)
        create_func: Function to create partner if not found

    Returns:
        The Odoo partner ID
    """
    # Search for existing partner
    existing_partners = odoo_client.search_read_sync(
        model=model,
        domain=domain,
        fields=["id"]
    )

    if existing_partners:
        # Existing partner found - update it
        partner_id = existing_partners[0]["id"]
        update_data = {k: v for k, v in partner_data.items(
        ) if k != "type" and k != "parent_id"}
        odoo_client.write(model=model, vals=update_data, record_id=partner_id)
        logger.info(f"Updated existing {partner_name} in Odoo: {partner_id}")
    else:
        # Create new partner
        if create_func:
            partner_id = create_func(partner_data, odoo_client=odoo_client)
            if not partner_id:
                logger.error(f"Failed to create {partner_name} in Odoo")
                return None
            logger.info(f"Created new {partner_name} in Odoo: {partner_id}")
        else:
            return None

    # Sync database record
    _sync_partner_with_database(
        odoo_id=partner_id,
        woo_id=woocommerce_id,
        email=customer_email,
        name=partner_data.get("name", ""),
        contact_type=contact_type,
        db=db,
        client_sync_repo=client_sync_repo,
        parent_id=parent_sync.id if parent_sync else None
    )

    return partner_id


# ==================== Celery Tasks ====================

class DatabaseTask(Task):
    """Base task with database session management."""
    db = None

    # @property
    # def db(self):
    #     if self._db is None:
    #         self._db = SessionLocal()
    #     return self._db

    def __call__(self, *args, **kwargs):
        self.db = SessionLocal()
        try:
            result = self.run(*args, **kwargs)
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            raise self.retry(exc=exc)
            raise
        finally:
            self.db.close()


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_product_to_odoo",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_product_to_odoo(self,
                         product_data: Dict[str, Any] = None,
                         instance_id: int = None,
                         delete: bool = False,
                         product_id: int = None
                         ) -> Dict[str, Any]:
    """
    Sync a single product from WooCommerce to Odoo.

    Args:
        product_data: WooCommerce product data dictionary
        instance_id: WooCommerce instance ID

    Returns:
        Dict with sync result
    """
    try:
        logger.info(
            f"Syncing product {product_data.get('id')} to Odoo (instance {instance_id})")

        # Get instance configuration
        from app.models.admin import WooCommerceInstance
        instance = self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()

        if not instance:
            logger.error(f"Instance {instance_id} not found")
            return {
                "success": False,
                "error": f"Instance {instance_id} not found"
            }
        if delete:
            sync_product = self.db.query(ProductSync).filter(
                ProductSync.woocommerce_id == product_data.get("id"),
                ProductSync.instance_id == instance_id
            ).first()
            if sync_product:
                variant_product_syncs = self.db.query(ProductVariantSync).filter(
                    ProductVariantSync.woocommerce_id == product_data.get(
                        "id"),
                    ProductVariantSync.instance_id == instance_id,
                    ProductVariantSync.product_tpl_id == sync_product.id
                ).all()
                for variant_sync in variant_product_syncs:
                    self.db.delete(variant_sync)
                    logger.info(
                        f"Deleted variant sync record {variant_sync.id} for WooCommerce product ID {product_data.get('id')}")
                    self.db.commit()
                self.db.delete(sync_product)
                self.db.commit()
                logger.info(
                    f"Deleted sync record for WooCommerce product ID {product_data.get('id')}")
            # else:
            #     logger.info(f"No sync record found for WooCommerce product ID {product_data.get('id')}, nothing to delete")
            #     variant_product_syncs = self.db.query(ProductVariantSync).filter(
            #         ProductVariantSync.woocommerce_id == product_data.get("id"),
            #         ProductVariantSync.instance_id == instance_id
            #     ).all()
            return {
                "success": True if sync_product else False,
                "action": "deleted",
                "odoo_id": None,
                "woocommerce_id": product_data.get("id"),
                "sku": product_data.get("sku")
            }
        # Initialize Odoo client with instance configuration
        client = OdooClient(
            instance.odoo_url,
            instance.odoo_db,
            instance.odoo_username,
            instance.odoo_password
        )
        # Map WooCommerce product to Odoo format
        odoo_product_data = {
            "name": product_data.get("name"),
            "default_code": product_data.get("sku"),
            "list_price": float(product_data.get("price", 0)),
            "type": woocommerce_type_to_odoo_type(product_data.get("type", "simple")),
            "active": product_data.get("status") == "publish",
        }

        # Check if product exists in Odoo
        sku = product_data.get("sku")
        woo_id = product_data.get("id")
        prododuct_sync = self.db.query(ProductSync).filter(
            ProductSync.woocommerce_id == woo_id,
            ProductSync.instance_id == instance_id
        ).first()
        existing_products = []
        if not prododuct_sync:
            logger.info(
                f"No existing sync record for WooCommerce product ID {woo_id}")
            return {
                "success": False,
                "action": "not_synced",
                "odoo_id": None,
                "woocommerce_id": product_data.get("id"),
                "sku": sku
            }
        if prododuct_sync:
            logger.info(
                f"Found sync record for WooCommerce product ID {woo_id}, Odoo ID {prododuct_sync.odoo_id}")

            existing_products = client.search_read_sync(
                model="product.template",
                domain=[("id", "=", prododuct_sync.odoo_id)],
                fields=["id", "name"]
            )
        if existing_products:
            # Update existing product
            product_id = existing_products[0]["id"]
            client.write(
                model="product.template", vals=odoo_product_data, record_id=product_id)
            action = "updated"
        else:
            # Create new product
            product_id = client.create(
                model="product.template", vals=odoo_product_data)
            action = "created"

        logger.info(f"Product {action}: Odoo ID {product_id}")

        return {
            "success": True,
            "action": action,
            "odoo_id": product_id,
            "woocommerce_id": product_data.get("id"),
            "sku": sku
        }

    except Exception as exc:
        logger.error(f"Error syncing product to Odoo: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_product_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_product_to_woocommerce(
    self,
    odoo_product_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    force_sync: bool = False
) -> Dict[str, Any]:
    """
    Sync a single product from Odoo to WooCommerce.

    Args:
        odoo_product_data: Odoo product data dictionary
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)
        create_if_not_exists: Create product if it doesn't exist
        update_existing: Update product if it exists
        force_sync: Force sync even if not modified

    Returns:
        Dict with sync result
    """
    try:
        logger.info(
            f"Syncing Odoo product {odoo_product_data.get('id')} to WooCommerce (instance {instance_id})")

        # Update initial progress
        update_task_progress(self, current=1, total=5,
                             message="Initializing sync")

        # Si no se proporcionan configuraciones, usar las de settings (fallback)
        if not odoo_config:
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }
        logger.info(f"ODOO CONFIG: {odoo_config}")
        odoo_client = OdooClient(
            odoo_config["url"],
            odoo_config["db"],
            odoo_config["username"],
            odoo_config["password"]
        )
        instance = self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id).first()
        # Normalize Odoo data (False -> None, many2one lists -> int)
        normalized_data = {}
        # logger.info(f"Normalizing Odoo product data: {odoo_product_data}")

        auth = odoo_client.web_authentication(odoo_client.url)
        cookies = auth.cookies.get_dict()
        image_helper = ImageHelper(session_id=cookies["session_id"])
        image_urls = []
        images_to_cleanup = []
        if 'image_1920' in odoo_product_data and odoo_product_data['image_1920']:
            product_image, file_path = image_helper.download_and_save_image(
                f"{odoo_config['url']}/web/image/product.template/{odoo_product_data['id']}/image_1920")
            image_urls.append(product_image)
            images_to_cleanup.append(file_path)
            normalized_data["image_urls"] = image_urls
        else:
            normalized_data["image_urls"] = image_urls
        logger.info(f"IMAGES URLS: {normalized_data['image_urls']}")
        for key, value in odoo_product_data.items():

            if key == 'is_published':
                normalized_data[key] = value
            elif value is False and key:
                normalized_data[key] = None
            elif isinstance(value, list):
                if key == 'categ_id' and len(value) == 2 and instance.category_from_product:
                    # many2one field [id, name] -> extract both id and name
                    normalized_data['categ_id'] = value[0] if isinstance(
                        value[0], int) else None
                    normalized_data['categ_name'] = value[1] if len(
                        value) > 1 else None
                    logger.info(
                        f"Extracted category: ID={normalized_data['categ_id']}, Name={normalized_data['categ_name']}")
                elif key == 'product_tag_ids' and value:
                    # many2many field - puede venir como [id1, id2, ...] o [[id, name], ...]
                    logger.info(
                        f"NORMALIZANDO product_tag_ids - Tipo: {type(value)}, Valor: {value}")
                    if value and isinstance(value[0], int):
                        # Es una lista de IDs, necesitamos consultar Odoo para obtener los nombres
                        logger.info(
                            f"product_tag_ids contiene solo IDs: {value}. Consultando nombres en Odoo...")
                        try:
                            # Conectar a Odoo para obtener los nombres de los tags
                            # Usar la versión síncrona de search_read
                            logger.info(
                                f"Llamando a search_read_sync para product.tag con IDs: {value}")
                            tags_data = odoo_client.search_read_sync(
                                'product.tag',
                                [['id', 'in', value]],
                                ['id', 'name']
                            )
                            logger.info(
                                f"Respuesta de Odoo para tags: {tags_data}")
                            normalized_data[key] = [
                                {
                                    "id": tag.get('id'),
                                    "name": tag.get('name', ''),
                                    "ks_woo_id": None
                                }
                                for tag in tags_data
                            ]
                            logger.info(
                                f"Extracted {len(normalized_data[key])} tags: {[t['name'] for t in normalized_data[key]]}")
                        except Exception as e:
                            logger.error(
                                f"Error consultando tags en Odoo: {e}", exc_info=True)
                            normalized_data[key] = []
                    elif value and isinstance(value[0], list):
                        # Ya viene como [[id, name], ...]
                        normalized_data[key] = [
                            {
                                "id": tag[0] if isinstance(tag, list) and len(tag) > 0 else tag,
                                "name": tag[1] if isinstance(tag, list) and len(tag) > 1 else "",
                                "ks_woo_id": None
                            }
                            for tag in value
                        ]
                        logger.info(
                            f"Extracted {len(normalized_data[key])} tags: {[t['name'] for t in normalized_data[key]]}")
                    else:
                        normalized_data[key] = []
                elif key == 'attribute_line_ids':
                    # many2many field for attributes - keep as is for now
                    normalized_data[key] = value
                elif key == 'taxes_id':
                    # many2many field for taxes - keep as is for now
                    normalized_data[key] = value
                elif key == 'public_categ_ids' and not instance.category_from_product:

                    categ_sync = self.db.query(CategorySync).filter(
                        CategorySync.odoo_id in value
                    ).all()
                    values_dic = [{'id': item.woocommerce_id}
                                  for item in categ_sync]
                    normalized_data[key] = values_dic
                elif len(value) == 2 and isinstance(value[0], int):
                    # Other many2one fields [id, name] -> extract id only
                    normalized_data[key] = value[0]
                # only process images if product is published
                elif key == 'product_template_image_ids':

                    for img in value:
                        image, file_path = image_helper.download_and_save_image(
                            f"{odoo_config['url']}/web/image/product.image/{img}/image_1920")

                        normalized_data["image_urls"].append(image)
                        images_to_cleanup.append(file_path)
                    # Special case for image URLs
                    logger.info(f"Processing image_urls field: {value}")
                else:
                    normalized_data[key] = value
            else:
                normalized_data[key] = value
        logger.info(f"IMAGES URLS: {normalized_data['image_urls']}")
        logger.info(f"NORMALIZED DATA: {odoo_product_data}")
        # normalized_data["image_urls"] = []
        # Generate globally unique slug: name + odoo_id + instance_id
        # This prevents slug conflicts across multiple instances
        base_slug = normalized_data["name"].replace(" ", "-").lower()
        odoo_id = str(normalized_data.get("id", ""))
        slug = f"{base_slug}-{odoo_id}-inst{instance_id}"
        logger.info(
            f"Generated globally unique slug: {slug} (instance: {instance_id})")
        normalized_data.update({
            "slug": slug
        })
        logger.info(
            f"Normalized data Odoo name: {normalized_data.get('name')}")

        # Convert to OdooProduct model
        odoo_product = OdooProduct(**normalized_data)
        logger.info(f"OdooProduct model created: {odoo_product}")
        # Crear wcapi desde wc_config si se proporcion\u00f3
        wcapi = None
        if wc_config:
            from woocommerce import API
            logger.info(f"Creating WooCommerce API client...")
            logger.info(f"WooCommerce config: {wc_config}")
            wcapi = API(
                url=wc_config["url"],
                consumer_key=wc_config["consumer_key"],
                consumer_secret=wc_config["consumer_secret"],
                wp_api=True,
                version="wc/v3",
                timeout=60,
                verify_ssl=False
            )

        # VARIANT INTEGRATION: Detect if product has variants
        product_has_variants = has_variants(normalized_data)
        logger.info(
            f"Product has variants: {product_has_variants}")
        is_variable = False
        product_attributes = None

        if product_has_variants:
            logger.info(
                f"Product {odoo_product.id} has variants, validating attributes...")

            # Update progress
            update_task_progress(self, current=2, total=5,
                                 message="Validating attributes")

            # Initialize Odoo client for validation
            odoo_client = OdooClient(
                url=odoo_config["url"],
                db=odoo_config["db"],
                username=odoo_config["username"],
                password=odoo_config["password"]
            )

            # Validate attributes are synced
            attribute_line_ids = normalized_data.get('attribute_line_ids', [])
            logger.info(f"Validating attribute lines: {attribute_line_ids}")
            validation = validate_attributes_synced(
                attribute_line_ids=attribute_line_ids,
                instance_id=instance_id,
                db=self.db,
                odoo_client=odoo_client
            )

            if not validation["valid"]:
                # Attributes not synced - fail with clear error
                error_msg = f"Cannot sync variable product: {len(validation['missing_attributes'])} attributes not synced"
                logger.error(error_msg)
                logger.error(
                    f"Missing attributes: {validation['missing_attributes']}")
                logger.error(f"Missing values: {validation['missing_values']}")

                return {
                    "success": False,
                    "action": "error",
                    "odoo_id": odoo_product.id,
                    "woocommerce_id": None,
                    "message": error_msg,
                    "error_details": {
                        "missing_attributes": validation['missing_attributes'],
                        "missing_values": validation['missing_values']
                    }
                }

            # Upload Images if needed
            if odoo_product.image_urls:
                logger.info(
                    f"Product {odoo_product.id} has {len(odoo_product.image_urls)} images to sync")
            # Attributes valid - prepare for variable product
            is_variable = True
            product_attributes = build_wc_attributes_for_product(
                attribute_line_ids=attribute_line_ids,
                instance_id=instance_id,
                db=self.db,
                odoo_client=odoo_client
            )
            logger.info(
                f"Product {odoo_product.id} configured as variable with {len(product_attributes)} attributes")

        # Update progress before WooCommerce sync
        update_task_progress(self, current=3, total=5,
                             message="Syncing to WooCommerce")

        # Convert to WooCommerce format
        wc_product_data = odoo_product_to_woocommerce(
            odoo_product,
            default_status="publish" if odoo_product.is_published else "draft",
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id,
            is_variable=is_variable,
            product_attributes=product_attributes,
            odoo_client=odoo_client
        )

        # Create or update in WooCommerce
        result = create_or_update_woocommerce_product(
            odoo_product=odoo_product,
            wc_product_data=wc_product_data,
            instance_id=instance_id,
            create_if_not_exists=create_if_not_exists,
            update_existing=update_existing,
            db=self.db,
            wcapi=wcapi
        )

        logger.info(f"Product sync result: {result.action}")

        # VARIANT INTEGRATION: Sync variations if variable product
        if is_variable and result.success and result.woocommerce_id:
            logger.info(
                f"Syncing variations for variable product {result.woocommerce_id}...")

            # Update progress for variations
            update_task_progress(self, current=4, total=5,
                                 message="Syncing product variations")

            variation_result = sync_product_variations_sync(
                odoo_client=odoo_client,
                template_id=odoo_product.id,
                wc_parent_id=result.woocommerce_id,
                db=self.db,
                wcapi=wcapi,
                instance_id=instance_id
            )

            # Update result with variant information
            result.is_variable = True
            result.has_variants = True
            result.variant_count = variation_result.get('total_variations', 0)
            result.variants_synced = variation_result.get('synced', 0)
            result.variants_updated = variation_result.get('updated')
            result.variants_failed = variation_result.get('failed', 0)
            result.variant_errors = variation_result.get('errors', [])

            if not variation_result.get('success', False):
                logger.warning(
                    f"Some variations failed to sync: {result.variants_failed}/{result.variant_count}")
                # Update message to reflect partial success
                result.message += f" (Variations: {result.variants_synced}/{result.variant_count} synced)"
            else:
                logger.info(
                    f"All {result.variants_synced} variations synced successfully")
                result.message += f" with {result.variants_synced} variations"

        # Final progress update
        update_task_progress(self, current=5, total=5,
                             message="Sync completed")
        image_helper.remove_local_image(images_to_cleanup)
        return {
            "success": result.success,
            "action": result.action,
            "odoo_id": result.odoo_id,
            "woocommerce_id": result.woocommerce_id,
            "message": result.message,
            "is_variable": result.is_variable,
            "variant_count": result.variant_count,
            "variants_synced": result.variants_synced,
            "variants_updated": result.variants_updated,
            "variants_failed": result.variants_failed
        }

    except Exception as exc:
        logger.error(f"Error syncing product to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.full_product_sync_wc_to_odoo",
    max_retries=1
)
@log_celery_task_with_retry
def full_product_sync_wc_to_odoo(
    self,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Perform full product catalog sync from WooCommerce to Odoo for a specific instance.

    Args:
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync statistics
    """
    page = 1
    per_page = 50
    total_processed = 0
    total_created = 0
    total_updated = 0
    total_errors = 0

    try:
        logger.info(
            f"Starting full product sync: WooCommerce -> Odoo (instance {instance_id})")

        # Use default config if not provided
        if not odoo_config:
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }

        # Create WooCommerce API client
        wcapi = create_wc_api_client(wc_config)

        while True:
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': total_processed,
                    'status': f'Processing page {page}'
                }
            )

            # Fetch products from WooCommerce using instance-specific config
            if wcapi:
                response = wc_request_with_logging(
                    "GET", "products",
                    wcapi=wcapi
                )
                data = response.json() if hasattr(response, 'json') else response
            if not data:
                break

            # Process each product
            for raw_product in data:
                try:
                    # Queue individual sync task
                    result = sync_product_to_odoo.apply_async(
                        args=[raw_product, instance_id],
                        queue="sync_queue",
                        retry=True,
                        headers={"parent_task_id": self.request.id}
                    )

                    # Wait for result (with timeout)
                    task_result = result.get(timeout=60)

                    if task_result.get("success"):
                        if task_result.get("action") == "created":
                            total_created += 1
                        elif task_result.get("action") == "updated":
                            total_updated += 1
                    else:
                        total_errors += 1

                    total_processed += 1

                except Exception as e:
                    logger.error(
                        f"Error processing product {raw_product.get('id')}: {e}")
                    total_errors += 1
                    total_processed += 1

            page += 1

        logger.info(
            f"Full sync completed: {total_processed} processed, "
            f"{total_created} created, {total_updated} updated, {total_errors} errors"
        )

        return {
            "success": True,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors,
            "status": "completed"
        }

    except Exception as exc:
        logger.error(f"Error in full product sync: {exc}")
        return {
            "success": False,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors + 1,
            "status": "error",
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.full_order_sync_wc_to_odoo",
    max_retries=1
)
@log_celery_task_with_retry
def full_order_sync_wc_to_odoo(
    self,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Perform full order catalog sync from WooCommerce to Odoo for a specific instance.

    Args:
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync statistics
    """
    page = 1
    per_page = 50
    total_processed = 0
    total_created = 0
    total_updated = 0
    total_errors = 0

    try:
        logger.info(
            f"Starting full order sync: WooCommerce -> Odoo (instance {instance_id})")

        # Use default config if not provided
        if not odoo_config:
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }

        # Create WooCommerce API client
        wcapi = create_wc_api_client(wc_config)

        while True:
            # Update task state
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': total_processed,
                    'status': f'Processing page {page}'
                }
            )

            # Fetch products from WooCommerce using instance-specific config
            data = None
            if wcapi:
                response = wc_request_with_logging(
                    "GET", "orders",
                    params={
                        "order": "asc",
                        "status": "completed"},
                    wcapi=wcapi
                )
                data = response

            if not data:
                break

            # Process each product
            for raw_order in data:
                try:
                    # Queue individual sync task
                    logger.info(f"ORDER DATA: {raw_order}")
                    logger.info(f"instance: {instance_id}")
                    result = sync_order_to_odoo.apply_async(
                        args=[raw_order, instance_id],
                        queue='sync_queue',
                        retry=True,
                        headers={"parent_task_id": self.request.id}
                    )

                    # Wait for result (with timeout)
                    task_result = result.get(timeout=60)

                    if task_result.get("success"):
                        if task_result.get("action") == "created":
                            total_created += 1
                        elif task_result.get("action") == "updated":
                            total_updated += 1
                    else:
                        total_errors += 1

                    total_processed += 1

                except Exception as e:
                    logger.error(
                        f"Error processing product {raw_order.get('id')}: {e}")
                    total_errors += 1
                    total_processed += 1

            page += 1

        logger.info(
            f"Full sync completed: {total_processed} processed, "
            f"{total_created} created, {total_updated} updated, {total_errors} errors"
        )

        return {
            "success": True,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors,
            "status": "completed"
        }

    except Exception as exc:
        logger.error(f"Error in full order sync: {exc}")
        return {
            "success": False,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors + 1,
            "status": "error",
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_order_to_odoo",
    max_retries=3,
    default_retry_delay=120
)
async def sync_order_to_odoo(self, order_data: Dict[str, Any], instance_id: int) -> Dict[str, Any]:
    """
    Sync a WooCommerce order to Odoo sale.order with proper partner/contact hierarchy.

    Structure:
    - Contact (type='contact'): Main customer record
      ├─ Billing Address (type='invoice'): Invoicing address
      └─ Shipping Address (type='delivery'): Delivery address (if different)

    Args:
        order_data: WooCommerce order data dictionary
        instance_id: WooCommerce instance ID

    Returns:
        Dict with sync result
    """
    try:
        logger.info(
            f"Syncing order {order_data.get('id')} to Odoo (instance {instance_id})")

        # Get instance configuration
        from app.models.admin import WooCommerceInstance
        instance = self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()

        if not instance:
            logger.error(f"Instance {instance_id} not found")
            return {"success": False, "error": f"Instance {instance_id} not found"}

        # Initialize clients
        client = OdooClient(
            instance.odoo_url,
            instance.odoo_db,
            instance.odoo_username,
            instance.odoo_password
        )
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret,
        }
        wcapi = create_wc_api_client(wc_config)

        # Extract order information
        wc_order_id = order_data.get("id")
        customer_id = order_data.get("customer_id")
        billing_address = order_data.get("billing", {})
        shipping_address = order_data.get("shipping", {})
        customer_email = billing_address.get("email", "")

        billing_odoo_partner_id = None
        shipping_odoo_partner_id = None
        odoo_contact_id = None
        contact_sync = None

        # Initialize repository once for all operations
        client_sync_repo = ClientSyncRepository(self.db)

        # Check if order already exists
        existing_orders = client.search_read_sync(
            "sale.order",
            domain=[("client_order_ref", "=", f"WC-{wc_order_id}")],
            fields=["id", 'state'],
            limit=1
        )
        if not customer_email or not customer_id:
            logger.warning(f"Order {wc_order_id} missing email or customer_id")
            return {"success": False, "error": "Missing email or customer_id"}

        # Fetch WooCommerce customer info
        woo_customer = wc_request_with_logging(
            "GET",
            f"customers/{customer_id}",
            wcapi=wcapi
        )
        woo_customer_id = woo_customer.get(
            "id") if woo_customer else customer_id

        # ========== STEP 1: Find or Create Contact (type='contact') ==========
        existing_contacts = client.search_read_sync(
            model="res.partner",
            domain=[("email", "=", customer_email), ("type", "=", "contact")],
            fields=["id"]
        )

        contact_name = f"{order_data.get('billing', {}).get('first_name', '')} {order_data.get('billing', {}).get('last_name', '')}".strip(
        )

        if existing_contacts:
            odoo_contact_id = existing_contacts[0]["id"]
            logger.info(f"Found existing contact in Odoo: {odoo_contact_id}")

            # Update existing contact data in Odoo
            client.write(
                model="res.partner",
                vals={"name": contact_name, "email": customer_email},
                record_id=odoo_contact_id
            )
            logger.info(f"Updated existing contact in Odoo: {odoo_contact_id}")
        else:
            # Create new contact
            contact_data = {
                "name": contact_name,
                "email": customer_email,
                "type": "contact"
            }
            logger.info(
                f"Creating new contact in Odoo with data: {contact_data}")
            odoo_contact_id = create_customer_in_odoo(
                contact_data, odoo_client=client)
            if not odoo_contact_id:
                logger.error("Failed to create contact in Odoo")
                return {"success": False, "error": "Failed to create contact"}
            logger.info(f"Created new contact in Odoo: {odoo_contact_id}")

        # Sync contact record in database
        contact_sync = _sync_partner_with_database(
            odoo_id=odoo_contact_id,
            woo_id=woo_customer_id,
            email=customer_email,
            name=contact_name,
            contact_type="contact",
            db=self.db,
            client_sync_repo=client_sync_repo
        )

        # ========== STEP 2: Find or Create Billing Address (type='invoice') ==========
        billing_name = f"{billing_address.get('first_name', '')} {billing_address.get('last_name', '')}".strip(
        )
        billing_partner_data = {
            "parent_id": odoo_contact_id,
            "name": billing_name,
            "email": customer_email,
            "phone": billing_address.get("phone", ""),
            "street": billing_address.get("address_1", ""),
            "street2": billing_address.get("address_2", ""),
            "city": billing_address.get("city", ""),
            "zip": billing_address.get("postcode", ""),
            "type": "invoice",
        }

        billing_odoo_partner_id = _handle_sync_partner(
            model="res.partner",
            domain=[
                ("parent_id", "=", odoo_contact_id),
                ("type", "=", "invoice"),
                ("email", "=", customer_email)
            ],
            partner_name="billing address",
            partner_data=billing_partner_data,
            contact_type="billing",
            woocommerce_id=woo_customer_id,
            customer_email=customer_email,
            odoo_client=client,
            db=self.db,
            client_sync_repo=client_sync_repo,
            parent_sync=contact_sync,
            create_func=create_customer_in_odoo
        )

        if not billing_odoo_partner_id:
            return {"success": False, "error": "Failed to sync billing address"}

        # ========== STEP 3: Find or Create Shipping Address (type='delivery') ==========
        is_shipping_different = (
            shipping_address.get("address_1") != billing_address.get("address_1") or
            shipping_address.get("city") != billing_address.get("city") or
            shipping_address.get("postcode") != billing_address.get("postcode")
        )

        if is_shipping_different:
            shipping_name = f"{shipping_address.get('first_name', '')} {shipping_address.get('last_name', '')}".strip(
            )
            shipping_partner_data = {
                "parent_id": odoo_contact_id,
                "name": shipping_name,
                "street": shipping_address.get("address_1", ""),
                "street2": shipping_address.get("address_2", ""),
                "city": shipping_address.get("city", ""),
                "zip": shipping_address.get("postcode", ""),
                "type": "delivery",
            }

            shipping_result = _handle_sync_partner(
                model="res.partner",
                domain=[
                    ("parent_id", "=", odoo_contact_id),
                    ("type", "=", "delivery")
                ],
                partner_name="shipping address",
                partner_data=shipping_partner_data,
                contact_type="shipping",
                woocommerce_id=woo_customer_id,
                customer_email=customer_email,
                odoo_client=client,
                db=self.db,
                client_sync_repo=client_sync_repo,
                parent_sync=contact_sync,
                create_func=create_customer_in_odoo
            )

            if not shipping_result:
                logger.warning(
                    "Failed to sync shipping address, using billing address")
                shipping_odoo_partner_id = billing_odoo_partner_id
            else:
                shipping_odoo_partner_id = shipping_result
        else:
            # Shipping same as billing
            shipping_odoo_partner_id = billing_odoo_partner_id
            logger.info(
                "Shipping address same as billing, using billing address")

        # ========== STEP 4: Create Order Lines ==========
        order_lines = []
        order_client = OrderClient(
            instance.odoo_url,
            instance.odoo_db,
            instance.odoo_username,
            instance.odoo_password
        )
        if existing_orders and existing_orders[0]['state'] == 'draft':
            order_client.write(
                model='sale.order',
                vals={
                    "order_line": [(5, 0, 0)],  # Remove existing lines
                },
                record_id=existing_orders[0]["id"]
            )
            action = "updated"
        if not existing_orders or existing_orders[0]['state'] == 'sent':
            for line in order_data.get("line_items", []):
                product_id = None
                # get taxes
                taxes_ids = []
                if line.get("taxes"):
                    taxes_ids = [t.get("id") for t in line.get("taxes")]
                logger.info(f"Taxes ids: {taxes_ids}")
                taxes_sync = self.db.query(TaxSync).filter(
                    TaxSync.woocommerce_id.in_(taxes_ids),
                    TaxSync.instance_id == instance_id
                ).all()
                logger.info(f"Taxes sync: {taxes_sync}")
                odoo_taxes_ids = [
                    t.odoo_id for t in taxes_sync] if taxes_sync else []
                logger.info(f"Odoo taxes ids: {odoo_taxes_ids}")
                # Try to find product by sync record first
                product_sync = None
                if line.get("product_id") and line.get("variation_id") != 0:
                    product_sync = self.db.query(ProductVariantSync).filter(
                        ProductVariantSync.woocommerce_id == line.get(
                            "variation_id"),
                        ProductVariantSync.instance_id == instance_id
                    ).first()
                    logger.info(
                        f"Found variant sync record: {product_sync.odoo_id if product_sync else 'None'} for variation_id {line.get('variation_id')}")
                else:
                    product_sync = self.db.query(ProductSync).filter(
                        ProductSync.woocommerce_id == line.get("product_id"),
                        ProductSync.instance_id == instance_id
                    ).first()
                    logger.info(
                        f"Searching for product sync record for product_id {line.get('product_id')}: {product_sync.odoo_id if product_sync else 'None'}")
                if product_sync:
                    products = client.search_read_sync(
                        "product.product" if line.get(
                            "variation_id") != 0 else "product.template",
                        domain=[("id", "=", product_sync.odoo_id)],
                        fields=["id", "product_variant_id"]
                    )
                    logger.info(
                        f"Found product in Odoo for sync record {product_sync.odoo_id}: {products}")
                    if products:
                        product_id = products[0]["product_variant_id"][0] if line.get(
                            "variation_id") == 0 else products[0]["id"]

                # Fallback: search by SKU
                if not product_id:
                    return {"success": False, "error": f"Product with id {line['product_id']} not synced"}

                if product_id:
                    order_lines.append((0, 0, {
                        "product_id": product_id,
                        "product_uom_qty": int(line.get("quantity", 1)),
                        "price_unit": float(line.get("price", 0)),
                        "name": line.get("name", "Product"),
                        "tax_id": odoo_taxes_ids
                    }))
            # Buscar  producto de de delivery in odoo
            delivery = client.search_read_sync(
                "product.product",
                domain=[("default_code", "=", "Delivery_007")],
                fields=["id", "name"],
                limit=1
            )
            if delivery:
                delivery = delivery[0]
                shipping_lines = order_data["shipping_lines"]
                if shipping_lines:
                    for shipping_line in shipping_lines:
                        order_lines.append((0, 0, {
                            "product_id": delivery["id"],
                            "product_uom_qty": 1,
                            "price_unit": shipping_line["total"],
                            "name": f"WC - Delivery - {shipping_line['method_title']}",
                        }))
        # Validate that we have at least one order line
        if not order_lines and not existing_orders: 
            logger.warning(
                f"No valid order lines found for order {wc_order_id}")
            return {"success": False, "error": "No valid order lines found"}

        # ========== STEP 5: Create or Update Sale Order ==========
        order_status = {
            "completed": "sale",
            "on-hold": "draft",
            "processing": "sale",
            "pending": "sent",
            "cancelled": "cancel",
            "checkout-draft": "draft"
        }
        sale_order_data = {
            "partner_id": billing_odoo_partner_id,
            "partner_shipping_id": shipping_odoo_partner_id,
            "client_order_ref": f"WC-{wc_order_id}",
            "note": order_data.get("customer_note", ""),
            "state": order_status[order_data["status"]]
        }
        sale_order_data.update({
            "order_line": order_lines
        }) if order_lines else None
        logger.info(f"Prepared sale order data for Odoo: {sale_order_data}")

        if existing_orders:
            logger.info(
                f"Order already exists in Odoo: {existing_orders[0]['id']}")
            order_id = existing_orders[0]["id"]
            order_state = existing_orders[0]['state']

            # Only update if order is in draft state
            # Orders in other states (sent, sale, done, cancelled) have restrictions
            if order_state == 'draft':
                try:

                    if order_data["status"] in ["processing", "completed"]:
                        order_client.cal_method(
                            model='sale.order',
                            metod='action_confirm',
                            params=[order_id]
                        )
                    order_client.write(
                        model='sale.order',
                        vals=sale_order_data,
                        record_id=order_id
                    )
                    # Create a regular invoice for the order
                    invoice, order_d = order_client.create_invoice(
                        order_id=order_id)
                    if invoice and order_d:
                        # create invoice payment
                        invoice_payment = order_client.create_invoice_payment(
                            invoice_id=invoice,
                            order=order_d)
                        if not invoice_payment:
                            logger.error("No payment found in Odoo")
                            message = f"The payment for the invoice {invoice} could not be created"
                            order_client.message_post(
                                model='sale.order',
                                record_id=order_id,
                                body=message
                            )
                    else:
                        logger.error(
                            f"No invoice found in Odoo for order {order_id}")
                        message = f"The invoice for the order {order_id} could not be created"
                        order_client.message_post(
                            model='sale.order',
                            record_id=order_id,
                            body=message
                        )
                    logger.info(
                        f"Updated existing order in draft state: {order_id}")
                    action = "updated"
                except Exception as update_exc:
                    logger.warning(
                        f"Failed to update order {order_id}: {update_exc}. "
                        f"Order will remain unchanged."
                    )
                    message = f"Order update failed: {update_exc}"

                    order_client.message_post(
                        model='sale.order',
                        record_id=order_id,
                        body=message
                    )
                    action = "existing"
            elif order_state in ['sent', 'sale']:
                logger.info(
                    f"Order {order_id} is in '{order_state}' state. "
                    f"Attempting to update note and order lines only."
                )
                try:
                    # if order_data["status"] == "processing" and order_state != 'sale':
                    #     order_client.cal_method(
                    #         model='sale.order',
                    #         metod='action_confirm',
                    #         params=[order_id]
                    #     )
                    #     order_client.write(
                    #         model='sale.order',
                    #         vals=sale_order_data,
                    #         record_id=order_id
                    #         )
                    # Update note
                    if order_data["status"] in ["pending", "processing", "on-hold"]:
                        logger.info(
                            f"Order {order_id} status is '{order_data['status']}', ensuring it is in draft state for update.")
                        message = f"There are inconsitens in the status order of off woocommerce and odoo."
                        update_order = wc_request_with_logging(
                            "POST",
                            f"orders/{wc_order_id}/notes",
                            params={
                                "note": message
                            },
                            wcapi=wcapi,
                        )
                        logger.info(
                            f"Send a note to WOO {update_order['author']}")
                        order_client.message_post(
                            model='sale.order',
                            record_id=order_id,
                            body=message
                        )
                    if order_data["status"] == "cancelled":
                        logger.info(
                            f"Order {order_id} status is 'cancelled', cancelling order in Odoo.")
                        message = f"This order was cancelled in WooCommerce. Cancelling in Odoo as well."
                        order_client.message_post(
                            model='sale.order',
                            record_id=order_id,
                            body=message
                        )

                    # Update order lines - this is more complex and may require custom logic
                    # For simplicity, we will not update order lines for non-draft orders in this example
                    logger.info(
                        f"Updated note for order {order_id} in '{order_state}' state. Order lines remain unchanged.")
                    action = "updated_note"
                except Exception as update_exc:
                    logger.warning(
                        f"Failed to update order {order_id}: {update_exc}. "
                        f"Order will remain unchanged."
                    )
                    message = f"Order update failed: {update_exc}"
                    order_client.message_post(
                        model='sale.order',
                        record_id=order_id,
                        body=message
                    )

                    action = "existing"
            else:
                logger.info(
                    f"Order {order_id} is in '{order_state}' state. "
                    f"Only draft orders can be updated. Order remains unchanged."
                )
                action = "existing"
        else:
            logger.info(
                f"Creating new sale order in Odoo for WooCommerce order {wc_order_id}")
            order_id = order_client.create(
                model="sale.order", vals=sale_order_data)
            if sale_order_data["state"] == "completed" or sale_order_data["state"] == "processing":
                order_client.cal_method(
                    model='sale.order',
                    metod='action_confirm',
                    params=[order_id]
                )
            logger.info(
                f"Created new sale order in Odoo with ID {order_id}")
            # if confirm order in Odoo if status is processing or completed create a invoice
            if sale_order_data["state"] == "completed" or sale_order_data["state"] == "processing":

                # Create a regular invoice for the order
                invoice, order_d = await order_client.create_invoice(
                    order_id=order_id)
                if invoice and order_d:
                    # create invoice payment
                    invoice_payment = order_client.create_invoice_payment(
                        invoice_id=invoice,
                        order=order_d)
                    if not invoice_payment:
                        logger.error("No payment found in Odoo")
                        message = f"The payment for the invoice {invoice} could not be created"
                        order_client.message_post(
                            model='sale.order',
                            record_id=order_id,
                            body=message
                        )
                else:
                    logger.error(
                        f"No invoice found in Odoo for order {order_id}")
                    message = f"The invoice for the order {order_id} could not be created"
                    order_client.message_post(
                        model='sale.order',
                        record_id=order_id,
                        body=message
                    )
            action = "created"

        logger.info(f"Order {action}: Odoo ID {order_id}")

        return {
            "success": True,
            "action": action,
            "odoo_id": order_id,
            "woocommerce_id": wc_order_id
        }

    except Exception as exc:
        logger.error(f"Error syncing order to Odoo: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_category_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_category_to_woocommerce(
    self,
    odoo_category_data: Dict[str, Any],
    categories: list,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single category from Odoo to WooCommerce.

    Args:
        odoo_category_data: Odoo category data dictionary (id, name, complete_name, parent_id)
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:

        logger.info(
            f"Syncing Odoo category {odoo_category_data.get('id')} to WooCommerce (instance {instance_id})")
        categories_by_id = {
            cat["id"]: {
                "id": cat["id"],
                "name": cat["name"],
                "parent_id": cat["parent_id"][0] if cat["parent_id"] else None
            }
            for cat in categories
        }
        logger.info(f"Categories by ID: {categories_by_id}")
        categories_to_sync = build_category_chain(
            odoo_category_data["id"], categories_by_id)
        # Crear wcapi desde wc_config si se proporcionó
        logger.info(
            f"Categories to sync (in order): {[cat['name'] for cat in categories_to_sync]}")
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        # Obtener ruta completa de categoría (complete_name incluye jerarquía)
        category_path = odoo_category_data.get(
            "complete_name") or odoo_category_data.get("name")

        # Exportar categoría a WooCommerce usando chain para ejecución secuencial
        logger.info(
            f"Creating task chain for {len(categories_to_sync)} categories: {[cat['name'] for cat in categories_to_sync]}")

        # Construir cadena usando el operador | (pipe) con .s() en lugar de .si()
        # Nota: Usamos .si() porque NO queremos pasar resultados entre tareas
        # cada categoría se sincroniza con sus propios parámetros
        signatures = []
        for i, cat in enumerate(categories_to_sync):
            sig = sync_category_hierarchy_to_woocommerce.si(
                cat, instance_id,
                odoo_config=odoo_config,
                wc_config=wc_config
            ).set(queue='sync_queue')
            signatures.append(sig)
            logger.info(
                f"Created signature for: {cat['name']} (position {i+1}/{len(categories_to_sync)})")

        # Usar chain() de celery.canvas para crear la cadena
        from celery import chain
        task_chain = chain(*signatures)

        # Ejecutar la cadena
        chain_result = task_chain.apply_async()

        logger.info(f"Chain started with final task ID: {chain_result.id}")

        if chain_result:
            return {
                "success": True,
                "action": "synced",
                "chain_id": str(chain_result.id),
                "category_count": len(categories_to_sync),
                "message": f"Category chain started for {category_path} ({len(categories_to_sync)} categories)"
            }
        else:
            logger.warning(
                f"Category sync returned no result: {category_path}")
            return {
                "success": False,
                "action": "failed",
                "children_tasks": [],
                "woocommerce_id": None,
                "message": f"Failed to sync category {category_path}"
            }

    except Exception as exc:
        logger.error(f"Error syncing category to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_category_hierarchy_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_category_hierarchy_to_woocommerce(
    self,
    odoo_category_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single category from Odoo to WooCommerce.

    Args:
        odoo_category_data: Odoo category data dictionary (id, name, complete_name, parent_id)
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:

        logger.info(
            f"Syncing Odoo category {odoo_category_data.get('id')} to WooCommerce (instance {instance_id})")

        # Determinar wc_parent_id si la categoría tiene padre
        wc_parent_id = None
        if odoo_category_data.get("parent_id"):
            parent_sync = self.db.query(CategorySync).filter(
                CategorySync.odoo_id == odoo_category_data["parent_id"],
                CategorySync.instance_id == instance_id
            ).first()

            if parent_sync:
                wc_parent_id = parent_sync.woocommerce_id
                logger.info(
                    f"Parent category found: Odoo {odoo_category_data['parent_id']} -> WC {wc_parent_id}")
            else:
                # En una cadena, esto no debería ocurrir porque las tareas son secuenciales
                logger.error(
                    f"Parent category {odoo_category_data['parent_id']} not found in sync table. "
                    f"This should not happen in a chain execution."
                )

        # Crear wcapi desde wc_config si se proporcionó
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        # Obtener ruta completa de categoría (complete_name incluye jerarquía)
        category_path = odoo_category_data.get(
            "complete_name") or odoo_category_data.get("name")
        odoo_category_id = odoo_category_data.get("id")

        # Exportar categoría a WooCommerce
        result = category_for_export(
            category_data=odoo_category_data,
            wc_parent_id=wc_parent_id,  # Ya calculado arriba
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id,
            odoo_config=odoo_config
        )

        if result and len(result) > 0:
            wc_category_id = result[0].get("id")
            logger.info(
                f"Category synced successfully: Odoo {odoo_category_id} -> WC {wc_category_id}")
            return {
                "success": True,
                "action": "synced",
                "odoo_id": odoo_category_id,
                "woocommerce_id": wc_category_id,
                "message": f"Category {category_path} synced successfully"
            }
        else:
            logger.warning(
                f"Category sync returned no result: {category_path}")
            return {
                "success": False,
                "action": "failed",
                "odoo_id": odoo_category_id,
                "woocommerce_id": None,
                "message": f"Failed to sync category {category_path}"
            }

    except Exception as exc:
        logger.error(f"Error syncing category to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


# ECOMMERCE CATEGORIES
@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_eco_category_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_eco_category_to_woocommerce(
    self,
    odoo_category_data: Dict[str, Any],
    categories: list,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single category from Odoo to WooCommerce.

    Args:
        odoo_category_data: Odoo category data dictionary (id, name, complete_name, parent_id)
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:

        logger.info(
            f"Syncing Odoo category {odoo_category_data.get('id')} to WooCommerce (instance {instance_id})")
        categories_by_id = {
            cat["id"]: {
                "id": cat["id"],
                "name": cat["name"],
                "parent_id": cat["parent_id"][0] if cat["parent_id"] else None,
                "image_1920": cat["image_1920"],
                "website_description": cat["website_description"],
            }
            for cat in categories
        }
        logger.info(f"Categories by ID: {categories_by_id}")
        categories_to_sync = build_category_chain(
            odoo_category_data["id"], categories_by_id)
        # Crear wcapi desde wc_config si se proporcionó
        logger.info(
            f"Categories to sync (in order): {[cat['name'] for cat in categories_to_sync]}")
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        # Obtener ruta completa de categoría (complete_name incluye jerarquía)
        category_path = odoo_category_data.get(
            "complete_name") or odoo_category_data.get("name")

        # Exportar categoría a WooCommerce usando chain para ejecución secuencial
        logger.info(
            f"Creating task chain for {len(categories_to_sync)} categories: {[cat['name'] for cat in categories_to_sync]}")

        # Construir cadena usando el operador | (pipe) con .s() en lugar de .si()
        # Nota: Usamos .si() porque NO queremos pasar resultados entre tareas
        # cada categoría se sincroniza con sus propios parámetros
        signatures = []
        for i, cat in enumerate(categories_to_sync):
            sig = sync_eco_category_hierarchy_to_woocommerce.si(
                cat, instance_id,
                odoo_config=odoo_config,
                wc_config=wc_config
            ).set(queue='sync_queue')
            signatures.append(sig)
            logger.info(
                f"Created signature for: {cat['name']} (position {i+1}/{len(categories_to_sync)})")

        # Usar chain() de celery.canvas para crear la cadena
        from celery import chain
        task_chain = chain(*signatures)

        # Ejecutar la cadena
        chain_result = task_chain.apply_async()

        logger.info(f"Chain started with final task ID: {chain_result.id}")

        if chain_result:
            return {
                "success": True,
                "action": "synced",
                "chain_id": str(chain_result.id),
                "category_count": len(categories_to_sync),
                "message": f"Category chain started for {category_path} ({len(categories_to_sync)} categories)"
            }
        else:
            logger.warning(
                f"Category sync returned no result: {category_path}")
            return {
                "success": False,
                "action": "failed",
                "children_tasks": [],
                "woocommerce_id": None,
                "message": f"Failed to sync category {category_path}"
            }

    except Exception as exc:
        logger.error(f"Error syncing category to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_eco_ category_hierarchy_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_eco_category_hierarchy_to_woocommerce(
    self,
    odoo_category_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single category from Odoo to WooCommerce.

    Args:
        odoo_category_data: Odoo category data dictionary (id, name, complete_name, parent_id)
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:

        logger.info(
            f"Syncing Odoo category {odoo_category_data.get('id')} to WooCommerce (instance {instance_id})")

        # Determinar wc_parent_id si la categoría tiene padre
        wc_parent_id = None
        if odoo_category_data.get("parent_id"):
            parent_sync = self.db.query(CategorySync).filter(
                CategorySync.odoo_id == odoo_category_data["parent_id"],
                CategorySync.instance_id == instance_id
            ).first()

            if parent_sync:
                wc_parent_id = parent_sync.woocommerce_id
                logger.info(
                    f"Parent category found: Odoo {odoo_category_data['parent_id']} -> WC {wc_parent_id}")
            else:
                # En una cadena, esto no debería ocurrir porque las tareas son secuenciales
                logger.error(
                    f"Parent category {odoo_category_data['parent_id']} not found in sync table. "
                    f"This should not happen in a chain execution."
                )

        # Crear wcapi desde wc_config si se proporcionó
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        # Obtener ruta completa de categoría (complete_name incluye jerarquía)
        category_path = odoo_category_data.get(
            "complete_name") or odoo_category_data.get("name")
        odoo_category_id = odoo_category_data.get("id")

        # Exportar categoría a WooCommerce
        result = category_for_export(
            category_data=odoo_category_data,
            wc_parent_id=wc_parent_id,  # Ya calculado arriba
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id,
            odoo_config=odoo_config
        )

        if result and len(result) > 0:
            wc_category_id = result[0].get("id")
            logger.info(
                f"Category synced successfully: Odoo {odoo_category_id} -> WC {wc_category_id}")
            return {
                "success": True,
                "action": "synced",
                "odoo_id": odoo_category_id,
                "woocommerce_id": wc_category_id,
                "message": f"Category {category_path} synced successfully"
            }
        else:
            logger.warning(
                f"Category sync returned no result: {category_path}")
            return {
                "success": False,
                "action": "failed",
                "odoo_id": odoo_category_id,
                "woocommerce_id": None,
                "message": f"Failed to sync category {category_path}"
            }

    except Exception as exc:
        logger.error(f"Error syncing category to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_tag_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.full_shipping_method_sync_odoo_to_woocommerce",
    max_retries=1
)
@log_celery_task_with_retry
def full_shipping_method_sync_odoo_to_woocommerce(
    self,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Perform full shipping method sync from Odoo to WooCommerce for a specific instance.

    This task uses the background_shipping_sync function but as a proper Celery task.

    Args:
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync statistics
    """
    # Generate a task ID for tracking
    import uuid
    task_id = str(uuid.uuid4())

    try:
        logger.info(
            f"Starting full shipping method sync: Odoo -> WooCommerce (instance {instance_id})")

        # Import here to avoid circular imports
        from app.services.woocommerce.shipping import background_shipping_sync
        from app.db.session import SessionLocal
        from app.models.admin import WooCommerceInstance

        # Get database session
        db = SessionLocal()

        try:
            # Get instance configuration
            instance = db.query(WooCommerceInstance).filter(
                WooCommerceInstance.id == instance_id
            ).first()

            if not instance:
                logger.error(f"Instance {instance_id} not found")
                return {
                    "success": False,
                    "error": f"Instance {instance_id} not found"
                }

            # Initialize WooCommerce API client
            if not wc_config:
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret
                }

            from app.services.woocommerce.client import get_wc_api_from_instance_config
            wcapi = get_wc_api_from_instance_config(wc_config)

            if not wcapi:
                logger.error("Could not initialize WooCommerce API client")
                return {
                    "success": False,
                    "error": "Could not initialize WooCommerce API client"
                }

            # Run the background shipping sync
            # Note: background_shipping_sync is async, so we need to handle that
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    background_shipping_sync(task_id=task_id, wcapi=wcapi)
                )
            finally:
                loop.close()

            # For now, we'll return a basic result since background_shipping_sync
            # doesn't return detailed stats. In a full implementation, we'd track these.
            return {
                "success": True,
                "task_id": task_id,
                "status": "started",
                "message": f"Shipping method sync started for instance {instance_id}"
            }

        finally:
            db.close()

    except Exception as exc:
        logger.error(f"Error in full shipping method sync: {exc}")
        return {
            "success": False,
            "task_id": task_id if 'task_id' in locals() else None,
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_shipping_method_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_shipping_method_to_woocommerce(
    self,
    odoo_carrier_data: Dict[str, Any],
    instance_id: int,
    zone_id: int = None,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single shipping method from Odoo to WooCommerce.

    Args:
        odoo_carrier_data: Odoo delivery carrier data dictionary
        instance_id: WooCommerce instance ID
        zone_id: Shipping zone ID (optional, will get/create default if not provided)
        create_if_not_exists: Create method if it doesn't exist
        update_existing: Update method if it exists
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:
        logger.info(
            f"Syncing Odoo shipping method {odoo_carrier_data.get('id')} to WooCommerce (instance {instance_id})")

        # Import here to avoid circular imports
        from app.services.woocommerce.shipping import (
            normalize_odoo_carrier,
            get_active_shipping_zone_id,
            create_or_update_woocommerce_shipping_method
        )
        from app.db.session import SessionLocal
        from app.models.admin import WooCommerceInstance

        # Get database session
        db = SessionLocal()

        try:
            # Get instance configuration
            instance = db.query(WooCommerceInstance).filter(
                WooCommerceInstance.id == instance_id
            ).first()

            if not instance:
                logger.error(f"Instance {instance_id} not found")
                return {
                    "success": False,
                    "error": f"Instance {instance_id} not found"
                }

            # Initialize WooCommerce API client
            if not wc_config:
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret
                }

            from app.services.woocommerce.client import get_wc_api_from_instance_config
            wcapi = get_wc_api_from_instance_config(wc_config)

            if not wcapi:
                logger.error("Could not initialize WooCommerce API client")
                return {
                    "success": False,
                    "error": "Could not initialize WooCommerce API client"
                }

            # Get or create shipping zone if not provided
            if not zone_id:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    zone_id_result = loop.run_until_complete(
                        get_active_shipping_zone_id(wcapi)
                    )
                    if not zone_id_result:
                        logger.error("Could not get or create shipping zone")
                        return {
                            "success": False,
                            "error": "Could not get or create shipping zone"
                        }
                    zone_id = zone_id_result["id"]
                finally:
                    loop.close()

            # Normalize carrier data
            normalized_carrier = normalize_odoo_carrier(odoo_carrier_data)

            # Sync the shipping method
            sync_result = create_or_update_woocommerce_shipping_method(
                odoo_carrier=normalized_carrier,
                wc_method_data={},  # Will be populated inside the function
                instance_id=instance_id,
                zone_id=zone_id,
                create_if_not_exists=create_if_not_exists,
                update_existing=update_existing,
                db=db,
                wcapi=wcapi
            )

            return sync_result

        finally:
            db.close()

    except Exception as exc:
        logger.error(f"Error syncing shipping method to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_tag_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_tag_to_woocommerce(
    self,
    odoo_tag_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sync a single tag from Odoo to WooCommerce.

    Args:
        odoo_tag_data: Odoo tag data dictionary (id, name)
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync result
    """
    try:
        from app.services.woocommerce import manage_tags_for_export, get_wc_api_from_instance_config

        logger.info(
            f"Syncing Odoo tag {odoo_tag_data.get('id')} to WooCommerce (instance {instance_id})")

        # Crear wcapi desde wc_config si se proporcionó
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        # Exportar tag a WooCommerce
        result = manage_tags_for_export(
            product_tags=[odoo_tag_data],
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id
        )

        if result and len(result) > 0:
            wc_tag_id = result[0].get("id")
            logger.info(
                f"Tag synced successfully: Odoo {odoo_tag_data.get('id')} -> WC {wc_tag_id}")
            return {
                "success": True,
                "action": "synced",
                "odoo_id": odoo_tag_data.get("id"),
                "woocommerce_id": wc_tag_id,
                "message": f"Tag {odoo_tag_data.get('name')} synced successfully"
            }
        else:
            logger.warning(
                f"Tag sync returned no result: {odoo_tag_data.get('name')}")
            return {
                "success": False,
                "action": "failed",
                "odoo_id": odoo_tag_data.get("id"),
                "woocommerce_id": None,
                "message": f"Failed to sync tag {odoo_tag_data.get('name')}"
            }

    except Exception as exc:
        logger.error(f"Error syncing tag to WooCommerce: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_tax_to_woocommerce",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_tax_to_woocommerce(
    self,
    odoo_tax_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None,
    create_if_not_exists: bool = True,
    update_existing: bool = True
) -> Dict[str, Any]:
    """
    Sync a single tax from Odoo to WooCommerce.

    Args:
        odoo_tax_data: Odoo tax data dictionary
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)
        create_if_not_exists: Create tax if it doesn't exist
        update_existing: Update tax if it exists

    Returns:
        Dict with sync result
    """
    try:
        logger.info(
            f"Syncing Odoo tax {odoo_tax_data.get('id')} to WooCommerce (instance {instance_id})")

        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        from app.services.woocommerce.taxes import sync_tax_to_woocommerce as sync_tax_func

        result = sync_tax_func(
            tax_data=odoo_tax_data,
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id,
            odoo_config=odoo_config,
            create_if_not_exists=create_if_not_exists,
            update_existing=update_existing
        )

        if result and result.get("success"):
            logger.info(
                f"Tax synced successfully: Odoo {odoo_tax_data.get('id')} -> WC {result.get('woocommerce_id')}")
            return {
                "success": True,
                "action": result.get("action", "synced"),
                "odoo_id": odoo_tax_data.get("id"),
                "woocommerce_id": result.get("woocommerce_id"),
                "name": result.get("name"),
                "rate": result.get("rate"),
                "message": f"Tax {result.get('name')} synced successfully"
            }
        else:
            logger.warning(
                f"Tax sync returned no result: {odoo_tax_data.get('name')}")
            return {
                "success": False,
                "action": "failed",
                "odoo_id": odoo_tax_data.get("id"),
                "woocommerce_id": None,
                "message": f"Failed to sync tax {odoo_tax_data.get('name')}"
            }

    except Exception as exc:
        logger.error(f"Error syncing tax to WooCommerce: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.full_tax_sync_odoo_to_woocommerce",
    max_retries=1
)
@log_celery_task_with_retry
def full_tax_sync_odoo_to_woocommerce(
    self,
    instance_id: int,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Perform full tax sync from Odoo to WooCommerce for a specific instance.

    Args:
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)

    Returns:
        Dict with sync statistics
    """
    total_processed = 0
    total_created = 0
    total_updated = 0
    total_errors = 0

    try:
        logger.info(
            f"Starting full tax sync: Odoo -> WooCommerce (instance {instance_id})")

        if not odoo_config:
            from app.models.admin import WooCommerceInstance
            instance = self.db.query(WooCommerceInstance).filter(
                WooCommerceInstance.id == instance_id
            ).first()
            if instance:
                odoo_config = {
                    "url": instance.odoo_url,
                    "db": instance.odoo_db,
                    "username": instance.odoo_username,
                    "password": instance.odoo_password
                }
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret
                }

        odoo_client = OdooClient(
            odoo_config["url"],
            odoo_config["db"],
            odoo_config["username"],
            odoo_config["password"]
        )

        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)

        from app.services.woocommerce.taxes import get_odoo_taxes

        taxes = get_odoo_taxes(
            odoo_client=odoo_client,
            domain=[["active", "=", True]],
            fields=["id", "name", "amount", "description",
                    "price_include", "type_tax_use", "active", "write_date"]
        )

        logger.info(f"Found {len(taxes)} taxes in Odoo")

        for tax in taxes:
            try:
                from app.services.woocommerce.taxes import sync_tax_to_woocommerce as sync_tax_func

                result = sync_tax_to_woocommerce(
                    tax_data=tax,
                    db=self.db,
                    wcapi=wcapi,
                    instance_id=instance_id,
                    odoo_config=odoo_config,
                    create_if_not_exists=True,
                    update_existing=True
                )

                if result and result.get("success"):
                    if result.get("action") == "created":
                        total_created += 1
                    elif result.get("action") == "updated":
                        total_updated += 1
                    total_processed += 1
                else:
                    total_errors += 1
                    total_processed += 1

            except Exception as e:
                logger.error(f"Error processing tax {tax.get('id')}: {e}")
                total_errors += 1
                total_processed += 1

        logger.info(
            f"Full tax sync completed: {total_processed} processed, "
            f"{total_created} created, {total_updated} updated, {total_errors} errors"
        )

        return {
            "success": True,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors,
            "status": "completed"
        }

    except Exception as exc:
        logger.error(f"Error in full tax sync: {exc}", exc_info=True)
        return {
            "success": False,
            "total_processed": total_processed,
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors + 1,
            "status": "error",
            "error": str(exc)
        }
