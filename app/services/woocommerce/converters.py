"""Data converters between Odoo and WooCommerce formats."""

import logging
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from woocommerce import API

from app.models.product_models import OdooProduct, WooCommerceProductCreate
from app.constants.woocommerce import WCProductType
from app.constants.odoo import OdooProductType
from app.services.woocommerce.categories import manage_category_for_export
from app.services.woocommerce.tags import manage_tags_for_export
from app.crud.odoo import OdooClient
from app.models.admin import WooCommerceInstance
from app.services.pricelist_service import PricelistService

__logger__ = logging.getLogger(__name__)


def _get_image_url(base_url, model_name, record_id, field_name, write_date=0, width=0, height=0):
    """ Returns a local url that points to the image field of a given browse record. """
    if base_url and not base_url.endswith("/"):
        base_url = base_url+"/"
    if width or height:
        return '%sweb/image/%s/%s/%s/%sx%s?unique=%s' % (base_url, model_name, record_id, field_name, width, height, fields.Datetime.to_string(write_date))
    else:
        return '%sweb/image/%s/%s/%s?unique=%s' % (base_url, model_name, record_id, field_name, fields.Datetime.to_string(write_date))


def woocommerce_type_to_odoo_type(wc_type: str) -> str:
    """
    Convert WooCommerce product type to Odoo product type.

    Args:
        wc_type: WooCommerce product type

    Returns:
        Odoo product type string
    """
    if wc_type in (WCProductType.SIMPLE, WCProductType.VARIABLE):
        return OdooProductType.CONSU
    elif wc_type in (WCProductType.GROUPED, WCProductType.EXTERNAL):
        return "combo"
    elif wc_type == "service":
        return OdooProductType.SERVICE
    return OdooProductType.PRODUCT  # Default


def manage_price_list_for_export(
    db: Session,
    odoo_client: OdooClient,
    product_id: int,
    product_tmpl_id: Optional[int],
    instance_id: int
) -> Optional[List[Dict[str, Any]]]:
    """
    Manage price list for export to WooCommerce.

    Args:
        price_list_id: Odoo price list ID
        db: Database session for tracking
        wcapi: WooCommerce API client
        instance_id: WooCommerce instance ID for multi-tenancy
    Returns:
        List of price rules formatted for WooCommerce or None if no price list
    """
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id).first()
    price_service = PricelistService(db)
    if instance.price_list:
        __logger__.info(f"Instance {instance_id} has price list configured: {instance.price_list.odoo_pricelist_id}. Calculating price for product {product_id}...")
        price = price_service.get_odoo_product_price(
            odoo_client=odoo_client,  # Not needed for price calculation
            product_id=product_id,
            product_tmpl_id=product_tmpl_id,
            pricelist_id=instance.price_list.odoo_pricelist_id
        )
        __logger__.info(f"Calculated price for product {product_id} using pricelist {instance.price_list.odoo_pricelist_id}: {price}")
        return price
    __logger__.info(f"No price list configured for instance {instance_id}, using product list price")
    return None


def odoo_product_to_woocommerce(
    odoo_product: OdooProduct,
    default_status: str = "publish",
    db: Session = None,
    wcapi: API = None,
    instance_id: Optional[int] = None,
    is_variable: bool = False,
    product_attributes: Optional[List[Dict[str, Any]]] = None,
    odoo_client: Optional[OdooClient] = None
) -> WooCommerceProductCreate:
    """
    Convert an Odoo product to WooCommerce format.

    Args:
        odoo_product: Odoo product object
        default_status: Default product status (publish/draft)
        db: Database session for category/tag tracking
        wcapi: WooCommerce API client
        instance_id: WooCommerce instance ID for multi-tenancy
        is_variable: True if product has variants
        product_attributes: Attributes for variable products

    Returns:
        WooCommerceProductCreate object ready for WooCommerce API
    """
    # Map product type
    product_type = "variable" if is_variable else "simple"
    if not is_variable and odoo_product.type == OdooProductType.SERVICE:
        product_type = WCProductType.SIMPLE  # Services are simple products in WC

    # Configure inventory
    manage_stock = odoo_product.qty_available is not None
    stock_quantity = int(
        odoo_product.qty_available) if odoo_product.qty_available else None

    # Configure price
    regular_price = None
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id).first()
    if instance.price_list:
        price = manage_price_list_for_export(
            db=db,
            odoo_client=odoo_client,
            product_id=odoo_product.product_variant_id or odoo_product.id,  # Use variant ID if available, otherwise template ID
            product_tmpl_id=odoo_product.id,
            instance_id=instance_id
        )
        regular_price = str(price) if price else None
    else:
        regular_price = str(
            odoo_product.list_price) if odoo_product.list_price else None
    # Configure categories with automatic creation if not exists
    categories = None
    if odoo_product.categ_name:
        __logger__.info(
            f"Product {odoo_product.name} has category: {odoo_product.categ_name}"
        )
        categories = manage_category_for_export(
            odoo_product.categ_name,
            db=db,
            odoo_category_id=odoo_product.categ_id,
            wcapi=wcapi,
            instance_id=instance_id
        )
        __logger__.info(f"Processed categories: {categories}")
    else:
        __logger__.warning(
            f"Product {odoo_product.name} has NO categ_name"
        )

    # Configure tags with automatic creation if not exists
    tags = None
    if odoo_product.product_tag_ids:
        __logger__.info(
            f"Product {odoo_product.name} has {len(odoo_product.product_tag_ids)} tags"
        )
        tags = manage_tags_for_export(
            odoo_product.product_tag_ids,
            db,
            wcapi=wcapi,
            instance_id=instance_id
        )
    else:
        __logger__.info(f"Product {odoo_product.name} has NO tags")

    # Configure images
    images = None
    if odoo_product.image_urls:
        images = [{"src": url} for url in odoo_product.image_urls]

    # Configure dimensions
    weight = str(odoo_product.weight) if odoo_product.weight else None
    dimensions = None
    if odoo_product.ks_length or odoo_product.ks_width or odoo_product.ks_height:
        dimensions = {
            "length": str(odoo_product.ks_length) if odoo_product.ks_length else "",
            "width": str(odoo_product.ks_width) if odoo_product.ks_width else "",
            "height": str(odoo_product.ks_height) if odoo_product.ks_height else ""
        }

    return WooCommerceProductCreate(
        name=odoo_product.name,
        type=product_type,
        regular_price=regular_price,
        description=odoo_product.description,
        short_description=odoo_product.description_sale,
        sku=odoo_product.default_code,
        slug=odoo_product.slug,
        manage_stock=manage_stock,
        stock_quantity=stock_quantity,
        in_stock=odoo_product.active and odoo_product.sale_ok,
        status=default_status if odoo_product.active else "draft",
        categories=categories,
        attributes=product_attributes,  # Add attributes for variable products,
        tags=tags,
        images=images,
        weight=weight,
        dimensions=dimensions
    )
