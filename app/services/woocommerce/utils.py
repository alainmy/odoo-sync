"""Legacy and utility functions for WooCommerce integration."""

import os
import logging
from typing import Dict
from app.schemas.schemas import TASKS, Product
from app.services.woocommerce.client import wc_request
from app.services.woocommerce.converters import woocommerce_type_to_odoo_type

__logger__ = logging.getLogger(__name__)


async def fetch_wc_product(product_id: int, wcapi=None) -> Product:
    """
    Fetch a WooCommerce product by ID.
    
    Args:
        product_id: WooCommerce product ID
        wcapi: WooCommerce API client
        
    Returns:
        Product object
    """
    data = wc_request("GET", f"products/{product_id}", wcapi=wcapi)
    return Product(
        id=data["id"],
        name=data.get("name"),
        sku=data.get("sku"),
        price=data.get("price"),
        status=data.get("status"),
        type=data.get("type"),
    )


async def background_full_sync(task_id: str, wcapi=None):
    """
    Background task for full product sync from WooCommerce to Odoo.
    
    Args:
        task_id: Unique task ID for tracking
        wcapi: WooCommerce API client
    """
    page = 1
    per_page = 50
    TASKS[task_id]["status"] = "running"
    TASKS[task_id]["processed"] = 0
    try:
        while True:
            data = wc_request(
                "GET", "/products",
                params={"page": page, "per_page": per_page},
                wcapi=wcapi
            )
            if not data:
                break
            for raw in data:
                product = Product(
                    id=raw["id"],
                    name=raw.get("name"),
                    sku=raw.get("sku"),
                    price=raw.get("price"),
                    status=raw.get("status"),
                    type=woocommerce_type_to_odoo_type(raw.get("type")),
                )
                push_to_odoo(product)
                TASKS[task_id]["processed"] += 1
            page += 1
        TASKS[task_id]["status"] = "finished"
    except Exception as e:
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["error"] = str(e)


def push_to_odoo(product: Product) -> bool:
    """
    Push a WooCommerce product to Odoo.
    
    Args:
        product: Product object to push
        
    Returns:
        True if successful, False otherwise
    """
    from app.core.config import settings
    from app.crud.odoo import OdooClient
    
    try:
        odoo_url = getattr(settings, 'ODOO_URL', None) or os.environ.get('ODOO_URL')
        odoo_db = getattr(settings, 'ODOO_DB', None) or os.environ.get('ODOO_DB')
        odoo_user = getattr(settings, 'ODOO_USERNAME', None) or os.environ.get('ODOO_USERNAME')
        odoo_pass = getattr(settings, 'ODOO_PASSWORD', None) or os.environ.get('ODOO_PASSWORD')
        
        client = OdooClient(odoo_url, odoo_db, odoo_user, odoo_pass)
        
        # Map WooCommerce product to Odoo product
        odoo_product_data = {
            "name": product.name,
            "default_code": product.sku,
            "list_price": product.price,
            "type": product.type or "product",
            "active": True,
        }
        
        product_id = client.create("product.product", odoo_product_data)
        return bool(product_id)
    except Exception as e:
        __logger__.error(f"Error inserting product in Odoo: {e}")
        return False
