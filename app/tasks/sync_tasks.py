"""
Celery tasks for synchronization operations between WooCommerce and Odoo.
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from celery import Task
from sqlalchemy.orm import Session
from app.celery_app import celery_app
from app.core.config import settings
from app.crud.odoo import OdooClient
from app.schemas.schemas import Product
from app.models.product_models import OdooProduct, WooCommerceProductCreate
from app.services.woocommerce import (
    wc_request,
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
from app.services.woocommerce import manage_category_for_export, \
    get_wc_api_from_instance_config, build_category_chain, category_for_export
from app.models.admin import CategorySync
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


# ==================== Celery Tasks ====================

class DatabaseTask(Task):
    """Base task with database session management."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.sync_tasks.sync_product_to_odoo",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_product_to_odoo(self, product_data: Dict[str, Any], instance_id: int) -> Dict[str, Any]:
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
        existing_products = []
        if sku:
            existing_products = client.search_read(
                "product.product",
                domain=[("default_code", "=", sku)],
                fields=["id", "name"]
            )

        if existing_products:
            # Update existing product
            product_id = existing_products[0]["id"]
            client.write("product.product", [product_id], odoo_product_data)
            action = "updated"
        else:
            # Create new product
            product_id = client.create("product.product", odoo_product_data)
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

        # Normalize Odoo data (False -> None, many2one lists -> int)
        normalized_data = {}
        # logger.info(f"Normalizing Odoo product data: {odoo_product_data}")
        for key, value in odoo_product_data.items():
            if value is False:
                normalized_data[key] = None
            elif isinstance(value, list):
                if key == 'categ_id' and len(value) == 2:
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
                            odoo_client = OdooClient(
                                odoo_config["url"],
                                odoo_config["db"],
                                odoo_config["username"],
                                odoo_config["password"]
                            )
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
                elif len(value) == 2 and isinstance(value[0], int):
                    # Other many2one fields [id, name] -> extract id only
                    normalized_data[key] = value[0]
                else:
                    normalized_data[key] = value
            else:
                normalized_data[key] = value

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
        odoo_client = None

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
            db=self.db,
            wcapi=wcapi,
            instance_id=instance_id,
            is_variable=is_variable,
            product_attributes=product_attributes
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
                response = wcapi.get("products", params={
                                     "page": page, "per_page": per_page})
                data = response.json() if hasattr(response, 'json') else response
            else:
                data = wc_request("GET", "products",
                                  params={"page": page, "per_page": per_page})

            if not data:
                break

            # Process each product
            for raw_product in data:
                try:
                    # Queue individual sync task
                    result = sync_product_to_odoo.apply_async(
                        args=[raw_product],
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
    name="app.tasks.sync_tasks.sync_order_to_odoo",
    max_retries=3,
    default_retry_delay=120
)
def sync_order_to_odoo(self, order_data: Dict[str, Any], instance_id: int) -> Dict[str, Any]:
    """
    Sync a WooCommerce order to Odoo sale.order.

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
            return {
                "success": False,
                "error": f"Instance {instance_id} not found"
            }

        # Initialize Odoo client with instance configuration
        client = OdooClient(
            instance.odoo_url,
            instance.odoo_db,
            instance.odoo_username,
            instance.odoo_password
        )

        # Extract order information
        wc_order_id = order_data.get("id")
        customer_email = order_data.get("billing", {}).get("email")

        # Find or create customer in Odoo
        partner_id = None
        if customer_email:
            partners = client.search_read(
                "res.partner",
                domain=[("email", "=", customer_email)],
                fields=["id"]
            )
            if partners:
                partner_id = partners[0]["id"]
            else:
                # Create partner
                partner_data = {
                    "name": f"{order_data.get('billing', {}).get('first_name', '')} "
                            f"{order_data.get('billing', {}).get('last_name', '')}",
                    "email": customer_email,
                    "phone": order_data.get("billing", {}).get("phone"),
                    "street": order_data.get("billing", {}).get("address_1"),
                    "city": order_data.get("billing", {}).get("city"),
                    "zip": order_data.get("billing", {}).get("postcode"),
                }
                partner_id = client.create("res.partner", partner_data)

        # Create sale order
        order_lines = []
        for line in order_data.get("line_items", []):
            # Find product in Odoo
            product_id = None
            if line.get("sku"):
                products = client.search_read(
                    "product.product",
                    domain=[("default_code", "=", line.get("sku"))],
                    fields=["id"]
                )
                if products:
                    product_id = products[0]["id"]

            if product_id:
                order_lines.append((0, 0, {
                    "product_id": product_id,
                    "product_uom_qty": line.get("quantity", 1),
                    "price_unit": float(line.get("price", 0)),
                    "name": line.get("name", "Product"),
                }))

        sale_order_data = {
            "partner_id": partner_id,
            "client_order_ref": f"WC-{wc_order_id}",
            "order_line": order_lines,
            "note": order_data.get("customer_note", ""),
        }

        # Check if order already exists
        existing_orders = client.search_read(
            "sale.order",
            domain=[("client_order_ref", "=", f"WC-{wc_order_id}")],
            fields=["id"]
        )

        if existing_orders:
            order_id = existing_orders[0]["id"]
            action = "existing"
        else:
            order_id = client.create("sale.order", sale_order_data)
            action = "created"

        logger.info(f"Order {action}: Odoo ID {order_id}")

        return {
            "success": True,
            "action": action,
            "odoo_id": order_id,
            "woocommerce_id": wc_order_id
        }

    except Exception as exc:
        logger.error(f"Error syncing order to Odoo: {exc}")
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
            instance_id=instance_id
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
