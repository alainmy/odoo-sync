import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.models.product_models import (
    OdooProduct,
    OdooToWooCommerceRequest,
    OdooToWooCommerceSyncResponse,
    ProductSyncResult,
    WooCommerceProductCreate,
    OdooCategory,
    CategorySyncResult,
    OdooCategoriesToWooCommerceRequest,
    OdooCategoriesToWooCommerceSyncResponse,
    WooCommerceCategoryCreate
)
import os
import requests
import logging
from app.core.config import settings
from app.schemas.schemas import TASKS, Product
from app.crud.admin import get_product_sync_by_odoo_id
from app.db.session import get_db
from woocommerce import API
from app.crud import crud_instance
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.factories.woocommerce_factory import WooCommerceClientFactory
from app.constants.woocommerce import WCProductType, WCProductStatus
from app.constants.odoo import OdooProductType
from app.repositories.product_sync_repository import ProductSyncRepository
from app.services.woocommerce.categories import manage_category_for_export
from app.services.woocommerce.tags import manage_tags_for_export

__logger__ = logging.getLogger(__name__)


def get_wc_api_from_instance_config(wc_config: Dict[str, str]) -> API:
    """
    Crea un cliente de WooCommerce API con las configuraciones de la instancia

    Args:
        wc_config: Dict con keys: url, consumer_key, consumer_secret

    Returns:
        API client configurado
    """
    return WooCommerceClientFactory.from_config(wc_config)


def get_wc_api_from_active_instance(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
) -> API:
    """
    Dependency injection que retorna un cliente de WooCommerce configurado
    con las credenciales de la instancia activa del usuario actual.

    Raises:
        HTTPException 404: Si el usuario no tiene una instancia activa
        HTTPException 500: Si hay error al crear el cliente
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(status_code=404, detail="No active instance found")

    try:
        return WooCommerceClientFactory.from_instance(instance)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create WooCommerce API client: {str(e)}"
        )


# def wc_request(method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
#     url = f"{WC_BASE_URL}{path}"
#     # Consumir siempre vía Nginx reverse proxy (https://woocommerce.localhost)
#     # Si el contenedor no resuelve woocommerce.localhost, usa la IP del host o agrega al /etc/hosts
#     auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
#     # headers = {
#     #     "User-Agent": "Mozilla/5.0",
#     #     "Host": "woocommerce_wordpress"
#     # }
#     # Permitir desactivar SSL verification para certificados autofirmados
#     verify_ssl = False if url.startswith("https://") else True
#     # r = requests.request(
#     #     method, url,
#     #     # headers=headers,
#     #     params=params, auth=auth, timeout=60, verify=False
#     # )
#     wcapi.verify_ssl = False if url.startswith("https://") else True
#     wcapi.is_ssl = False if url.startswith("https://") else True
#     r = wcapi.get(path)
#     if not r.ok:
#         raise HTTPException(status_code=r.status_code,
#                             detail=f"WooCommerce error: {r.text}")
#     return r.json()

def wc_get(method: str,
           path: str,
           params: Optional[Dict[str, Any]] = None,
           wcapi: API = None) -> Any:

    r = wcapi.get(endpoint=path, params=params)
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=f"WooCommerce error: {r.text}")
    return r.json()


def wc_post(method: str,
            path: str,
            params: Optional[Dict[str, Any]] = None,
            wcapi: API = None) -> Any:
    r = wcapi.post(path, params)
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=f"WooCommerce error: {r.text}")
    return r.json()


def wc_put(method: str,
           path: str,
           params: Optional[Dict[str, Any]] = None,
           wcapi: API = None) -> Any:
    r = wcapi.put(path, params)
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=f"WooCommerce error: {r.text}")
    return r.json()


def wc_delete(method: str,
              path: str,
              params: Optional[Dict[str, Any]] = None,
              wcapi: API = None) -> Any:
    r = wcapi.delete(path)
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=f"WooCommerce error: {r.text}")
    return r.json()


def wc_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, wcapi: API = None) -> Any:
    # Fallback a settings si no se proporciona wcapi
    if wcapi is None:
        wcapi = API(
            url=settings.wc_base_url,
            consumer_key=settings.wc_consumer_key,
            consumer_secret=settings.wc_consumer_secret,
            wp_api=True,
            version="wc/v3",
            timeout=60,
            verify_ssl=False
        )

    response_json = None
    if method == "GET":
        response_json = wc_get(method, path, params, wcapi)
    if method == "POST":
        response_json = wc_post(method, path, params, wcapi)
    if method == "PUT":
        response_json = wc_put(method, path, params, wcapi)
    if method == "DELETE":
        response_json = wc_delete(method, path, params, wcapi)
    return response_json


def wc_request_post(method: str, path: str, data: Optional[Dict[str, Any]] = None, wcapi: API = None) -> Any:
    # Fallback a settings si no se proporciona wcapi
    if wcapi is None:
        wcapi = API(
            url=settings.wc_base_url,
            consumer_key=settings.wc_consumer_key,
            consumer_secret=settings.wc_consumer_secret,
            wp_api=True,
            version="wc/v3",
            timeout=60,
            verify_ssl=False
        )

    url = f"{wcapi.url}{path}"
    # Consumir siempre vía Nginx reverse proxy (https://woocommerce.localhost)
    # Si el contenedor no resuelve woocommerce.localhost, usa la IP del host o agrega al /etc/hosts
    auth = (wcapi.consumer_key, wcapi.consumer_secret)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Host": "woocommerce.localhost"
    }
    # Permitir desactivar SSL verification para certificados autofirmados
    r = requests.request(
        method, url, headers=headers,
        json=data, auth=auth, timeout=60, verify=False
    )
    if not r.ok:
        raise HTTPException(status_code=r.status_code,
                            detail=f"WooCommerce error: {r.text}")
    return r.json()


async def fetch_wc_product(product_id: int) -> Product:
    data = await wc_request("GET", f"products/{product_id}")
    return Product(
        id=data["id"],
        name=data.get("name"),
        sku=data.get("sku"),
        price=data.get("price"),
        status=data.get("status"),
        type=data.get("type"),
    )


def woocommerce_type_to_odoo_type(wc_type: str) -> str:
    if wc_type in ("simple", "variable"):
        return "consu"
    elif wc_type in ("grouped", "external"):
        return "combo"
    elif wc_type == "service":
        return "service"
    return "product"  # valor por defecto


async def background_full_sync(task_id: str):
    page = 1
    per_page = 50
    TASKS[task_id]["status"] = "running"
    TASKS[task_id]["processed"] = 0
    try:
        while True:
            data = await wc_request("GET", "/products",
                                    params={"page": page, "per_page": per_page})
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
    # Implementar inserción real en Odoo
    # Se asume que existe OdooClient y la sesión se obtiene de settings o contexto
    from app.core.config import settings
    from app.crud.odoo import OdooClient
    try:
        odoo_url = getattr(settings, 'ODOO_URL',
                           None) or os.environ.get('ODOO_URL')
        odoo_db = getattr(settings, 'ODOO_DB',
                          None) or os.environ.get('ODOO_DB')
        odoo_user = getattr(settings, 'ODOO_USERNAME',
                            None) or os.environ.get('ODOO_USERNAME')
        odoo_pass = getattr(settings, 'ODOO_PASSWORD',
                            None) or os.environ.get('ODOO_PASSWORD')
        client = OdooClient(odoo_url, odoo_db, odoo_user, odoo_pass)
        # Mapear el producto de WooCommerce a OdooProduct
        odoo_product_data = {
            "name": product.name,
            "default_code": product.sku,
            "list_price": product.price,
            "type": product.type or "product",
            "active": True,
        }
        # Puedes agregar más campos según tu modelo y necesidades
        product_id = client.create("product.product", odoo_product_data)
        return bool(product_id)
    except Exception as e:
        logging.error(f"Error insertando producto en Odoo: {e}")
        return False


def odoo_product_to_woocommerce(
    odoo_product: OdooProduct,
    default_status: str = "publish",
    db: Session = None,
    wcapi: API = None,
    instance_id: Optional[int] = None,
    is_variable: bool = False,
    product_attributes: Optional[List[Dict[str, Any]]] = None
) -> WooCommerceProductCreate:
    """Convierte un producto de Odoo al formato de WooCommerce"""

    # Mapear tipo de producto
    product_type = "variable" if is_variable else "simple"  # Variable si tiene variantes
    if not is_variable and odoo_product.type == "service":
        product_type = "simple"  # Los servicios en WooCommerce son productos simples

    # Configurar inventario
    manage_stock = odoo_product.qty_available is not None
    stock_quantity = int(
        odoo_product.qty_available) if odoo_product.qty_available else None

    # Configurar precio
    regular_price = str(
        odoo_product.list_price) if odoo_product.list_price else None

    # Configurar categorías con creación automática si no existe
    categories = None
    if odoo_product.categ_name:
        __logger__.info(
            f"Producto {odoo_product.name} tiene categoría: {odoo_product.categ_name}")
        categories = manage_category_for_export(
            odoo_product.categ_name,
            db=db,
            odoo_category_id=odoo_product.categ_id,
            wcapi=wcapi,
            instance_id=instance_id
        )
        __logger__.info(f"Categorías procesadas: {categories}")
    else:
        __logger__.warning(f"Producto {odoo_product.name} NO tiene categ_name")

    # Configurar tags con creación automática si no existe
    tags = None
    if odoo_product.product_tag_ids:
        __logger__.info(
            f"Producto {odoo_product.name} tiene {len(odoo_product.product_tag_ids)} tags")
        tags = manage_tags_for_export(
            odoo_product.product_tag_ids, db, wcapi=wcapi, instance_id=instance_id)
    else:
        __logger__.info(f"Producto {odoo_product.name} NO tiene tags")

    # Configurar imágenes
    images = None
    if odoo_product.image_urls:
        images = [{"src": url} for url in odoo_product.image_urls]

    # Configurar dimensiones
    weight = str(odoo_product.weight) if odoo_product.weight else None
    dimensions = None
    if odoo_product.ks_length or odoo_product.ks_width or odoo_product.ks_height:
        dimensions = {
            "length": str(odoo_product.ks_length) if odoo_product.ks_length else "",
            "width": str(odoo_product.ks_width) if odoo_product.ks_width else "",
            "height": str(odoo_product.ks_height) if odoo_product.ks_height else ""
        }

    # Prepare attributes for variable products
    attributes_data = None
    if is_variable and product_attributes:
        attributes_data = product_attributes
        __logger__.info(
            f"Product {odoo_product.name} configured as variable with {len(product_attributes)} attributes")

    return WooCommerceProductCreate(
        name=odoo_product.name,
        type=product_type,
        regular_price=regular_price,
        description=odoo_product.description,
        short_description=odoo_product.description_sale,
        sku=odoo_product.default_code,
        manage_stock=manage_stock,
        stock_quantity=stock_quantity,
        in_stock=odoo_product.active and odoo_product.sale_ok,
        status=default_status if odoo_product.active else "draft",
        categories=categories,
        tags=tags,
        images=images,
        weight=weight,
        dimensions=dimensions,
        attributes=attributes_data,
        slug=odoo_product.name.lower().replace(" ", "-") + str(odoo_product.id)
    )
