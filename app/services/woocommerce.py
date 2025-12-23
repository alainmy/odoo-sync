import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
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

WC_BASE_URL = settings.wc_base_url
WC_CONSUMER_KEY = settings.wc_consumer_key
WC_CONSUMER_SECRET = settings.wc_consumer_secret
wcapi = API(
    url=WC_BASE_URL,
    consumer_key=WC_CONSUMER_KEY,
    consumer_secret=WC_CONSUMER_SECRET,
    wp_api=True,
    version="wc/v3",
    timeout=60,
    # is_ssl=True,
    # Force Basic Authentication as query string true and using under HTTPS
    # query_string_auth=True,

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

    r = wcapi.get(path)
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


def wc_request(method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{WC_BASE_URL}{path}"
    wcapi.verify_ssl = False if url.startswith("https://") else True
    wcapi.is_ssl = False if url.startswith("https://") else True
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


def wc_request_post(method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{WC_BASE_URL}{path}"
    # Consumir siempre vía Nginx reverse proxy (https://woocommerce.localhost)
    # Si el contenedor no resuelve woocommerce.localhost, usa la IP del host o agrega al /etc/hosts
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
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


async def odoo_product_to_woocommerce(odoo_product: OdooProduct, default_status: str = "publish") -> WooCommerceProductCreate:
    """Convierte un producto de Odoo al formato de WooCommerce"""

    # Mapear tipo de producto
    product_type = "simple"  # Por defecto simple
    if odoo_product.type == "service":
        product_type = "simple"  # Los servicios en WooCommerce son productos simples

    # Configurar inventario
    manage_stock = odoo_product.qty_available is not None
    stock_quantity = int(
        odoo_product.qty_available) if odoo_product.qty_available else None

    # Configurar precio
    regular_price = str(
        odoo_product.list_price) if odoo_product.list_price else None

    # Configurar categorías si existe
    categories = None
    if odoo_product.categ_name:
        name = odoo_product.categ_name.split("/")[-1].strip()
        slug = name.replace(" ", "-").lower()
        category = await wc_request("GET", f"products/categories?search={slug}")
        if category:
            categories = [
                {"id": category[0]["id"], "name": name, "slug": slug}]

    # Configurar imágenes
    images = None
    if odoo_product.image_urls:
        images = [{"src": url} for url in odoo_product.image_urls]

    # Configurar dimensiones
    weight = str(odoo_product.weight) if odoo_product.weight else None

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
        images=images,
        weight=weight
    )


async def find_woocommerce_product_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    """Busca un producto en WooCommerce por SKU"""
    if not sku:
        return None

    try:
        # Buscar por SKU
        products = await wc_request("GET", "/products",
                              params={"sku": sku, "per_page": 1})
        return products[0] if products else None
    except Exception as e:
        logging.error(f"Error buscando producto por SKU {sku}: {e}")
        return None


async def find_woocommerce_product_by_id(id: int) -> Optional[Dict[str, Any]]:
    """Busca un producto en WooCommerce por SKU"""
    if not int:
        return None

    try:
        # Buscar por SKU
        products = await wc_request("GET", f"products/{id}")
        return products if products else None
    except Exception as e:
        logging.error(f"Error buscando producto por SKU {id}: {e}")
        return None


async def create_or_update_woocommerce_product(
    odoo_product: OdooProduct,
    wc_product_data: WooCommerceProductCreate,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    db: Session = None
) -> ProductSyncResult:
    """Crea o actualiza un producto en WooCommerce"""

    result = ProductSyncResult(
        odoo_id=odoo_product.id,
        odoo_sku=odoo_product.default_code,
        success=False,
        action="skipped",
        message="No procesado"
    )

    try:
        # Buscar producto existente por SKU
        existing_product = None
        if odoo_product.default_code:
            existing_product = find_woocommerce_product_by_sku(
                odoo_product.default_code)
        else:
            sync_product = get_product_sync_by_odoo_id(db, odoo_product.id)
            if sync_product:
                existing_product = find_woocommerce_product_by_id(
                    sync_product.woocommerce_id)
        # Convertir el modelo Pydantic a diccionario para la API
        product_data = wc_product_data.dict(exclude_none=True)

        if existing_product:
            # Producto existe
            result.woocommerce_id = existing_product["id"]

            if update_existing:
                # Actualizar producto existente
                updated_product = await wc_request(
                    "PUT",
                    f"products/{existing_product['id']}",
                    data=product_data
                )
                result.success = True
                result.action = "updated"
                result.message = f"Producto actualizado: {updated_product['name']}"
                result.woocommerce_id = updated_product["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Producto existe, actualización deshabilitada"
        else:
            # Producto no existe
            if create_if_not_exists:
                # Crear nuevo producto
                new_product = await wc_request(
                    "POST", "/products", data=product_data)
                result.success = True
                result.action = "created"
                result.message = f"Producto creado: {new_product['name']}"
                result.woocommerce_id = new_product["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Producto no existe, creación deshabilitada"

    except HTTPException as e:
        result.success = False
        result.action = "error"
        result.message = f"Error HTTP: {e.detail}"
        result.error_details = str(e)
    except Exception as e:
        result.success = False
        result.action = "error"
        result.message = f"Error inesperado: {str(e)}"
        result.error_details = str(e)
        logging.error(f"Error sincronizando producto {odoo_product.name}: {e}")

    return result


# ==================== CATEGORÍAS ====================


async def find_woocommerce_category_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Busca una categoría en WooCommerce por nombre exacto"""
    try:
        categories = await wc_request("GET", "products/categories",
                                params={"search": name, "per_page": 100})
        # Buscar coincidencia exacta
        for cat in categories:
            if cat.get("name", "").lower() == name.lower():
                return cat
        return None
    except Exception as e:
        logging.error(f"Error buscando categoría por nombre {name}: {e}")
        return None


async def find_category_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Busca una categoría en WooCommerce por slug"""
    try:
        categories = await wc_request("GET", f"products/categories?slug={slug}")
        # Buscar coincidencia exacta
        for cat in categories:
            if cat.get("slug", "").lower() == slug.lower():
                return cat
        return None
    except Exception as e:
        logging.error(f"Error buscando categoría por slug {slug}: {e}")
        return None


async def create_or_update_woocommerce_category(
    odoo_category: OdooCategory,
    wc_category_data: WooCommerceCategoryCreate,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    categories_map: Dict[int, int] = None
) -> CategorySyncResult:
    """Crea o actualiza una categoría en WooCommerce"""

    result = CategorySyncResult(
        odoo_id=odoo_category.id,
        odoo_name=odoo_category.name,
        success=False,
        action="skipped",
        message="No procesado"
    )

    try:
        # Buscar categoría existente por nombre
        existing_category = await find_woocommerce_category_by_name(
            odoo_category.name)

        # Convertir el modelo Pydantic a diccionario
        category_data = wc_category_data.dict(exclude_none=True)

        # Si hay categoría padre, buscar su ID en WooCommerce
        if odoo_category.parent_id and categories_map:
            wc_parent_id = categories_map.get(odoo_category.parent_id)
            if wc_parent_id:
                category_data["parent"] = wc_parent_id
            else:
                logging.warning(
                    f"Categoría padre {odoo_category.parent_id} "
                    f"no encontrada en el mapa"
                )

        if existing_category:
            # Categoría existe
            result.woocommerce_id = existing_category["id"]

            if update_existing:
                # Actualizar categoría existente
                updated_category = await wc_request(
                    "PUT",
                    f"products/categories/{existing_category['id']}",
                    params=category_data
                )
                result.success = True
                result.action = "updated"
                result.message = (
                    f"Categoría actualizada: {updated_category['name']}"
                )
                result.woocommerce_id = updated_category["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Categoría existe, actualización deshabilitada"
        else:
            # Categoría no existe
            if create_if_not_exists:
                # Crear nueva categoría
                new_category = await wc_request(
                    "POST", "products/categories", params=category_data)
                result.success = True
                result.action = "created"
                result.message = f"Categoría creada: {new_category['name']}"
                result.woocommerce_id = new_category["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Categoría no existe, creación deshabilitada"

    except HTTPException as e:
        result.success = False
        result.action = "error"
        result.message = f"Error HTTP: {e.detail}"
        result.error_details = str(e)
    except Exception as e:
        result.success = False
        result.action = "error"
        result.message = f"Error inesperado: {str(e)}"
        result.error_details = str(e)
        logging.error(
            f"Error sincronizando categoría {odoo_category.name}: {e}")

    return result
