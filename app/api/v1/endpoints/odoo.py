from app.session import create_session, get_session
from app.schemas.products import ProductBase
from app.schemas.categories import CategoryBase, CategorySyncRequest, CategorySyncResponse
from app.crud.odoo import OdooClient
import json
import os
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, Header
from typing import List, Optional
import dotenv
import requests
import logging
from app.core.config import settings
dotenv.load_dotenv()


_logger = logging.getLogger(__name__)

# Dependency para documentar api_session como header global
async def api_session_header(api_session: str = Header(..., description="Token de sesión Odoo (header)")):
    return api_session

router = APIRouter(
    dependencies=[Depends(api_session_header)]
)

ODOO_URL = "http://host.docker.internal:8069"
ODOO_DB = "c4e"
ODOO_USERNAME = "admin"
ODOO_PASSWORD = "admin"


default_context = {
    "lang": "en_US",
    "tz": "America/Havana",
    "allowed_company_ids": [1],
    "uid": 4
}


async def get_session_id(request: Request):
    api_session = request.headers.get("api-session") or request.headers.get("api_session")
    if api_session:
        session = await get_session(request)
        # if not session:
        #     raise HTTPException(
        #             status_code=401, detail="Session not found")
        if session:
            # if not session.is_valid() and session.expiry_date:
            #     raise HTTPException(
            #             status_code=401, detail="Session expired")
            session_data = json.loads(session)
            session_data.update({
                "password": settings.odoo_password,
                "username": settings.odoo_username
            })
            session_data["context"].update({
                "lang": request.headers.get("lang", "en_US"),
                "tz": request.headers.get("tz", "America/Havana"),
                "website_id": request.headers.get("website_id", 1),
                "allowed_company_ids": [1],
                "uid": session_data.get("uid", 2),

            })
            await create_session(api_session, session_data)
            odoo = OdooClient(url=settings.odoo_url,
                              db=settings.odoo_db,
                              username=session_data["username"],
                              password=session_data["password"] or settings.odoo_password,
                              context=session_data["context"])
            return odoo
        else:
            session_data = {
                "password": settings.odoo_password,
                "username": settings.odoo_username,
                "context": default_context
            }
            await create_session(api_session, session_data)
            odoo = OdooClient(url=settings.odoo_url,
                              db=settings.odoo_db,
                              username=session_data["username"],
                              password=session_data["password"],
                              context=session_data["context"])
            return odoo


@router.get("/odoo/products", summary="Consultar productos en Odoo",
            response_model=List[ProductBase])
async def get_odoo_products(
    request: Request,
    name: Optional[str] = Query(
        None, description="Filtrar por nombre de producto"),
    limit: int = Query(
        100, ge=1, le=100, description="Limite de productos a retornar"),
    offset: int = Query(
        0, ge=0,
        description="Offset de productos a retornar"),
    odoo: str = Depends(get_session_id),
):
    try:
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="No se pudo autenticar")
        domain = []
        if name:
            domain.append(["name", "ilike", name])
        products = await odoo.search_read(uid,
                                          "product.template",
                                          domain=domain,
                                          limit=limit,
                                          fields=[
                                              "id", "name", "list_price",
                                              "description", "image_1920",
                                              "categ_id", "sale_ok",
                                              "uom_id", 
                                              "uom_po_id",
                                              "uom_category_id",
                                              "weight",
                                              "weight_uom_name",
                                              "volume", "volume_uom_name",
                                          ],
                                          offset=offset)
        if products.get("error"):
            raise HTTPException(
                status_code=400, detail=products["error"]["message"])
        return [ProductBase.from_odoo(product) for product in products["result"]]
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/odoo/products/{product_id}/detail", summary="Consultar producto en Odoo",
            response_model=ProductBase)
async def get_odoo_product(
    request: Request,
    product_id: int,
    odoo: str = Depends(get_session_id),
):
    try:
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="No se pudo autenticar")
        domain = [
            ["id", "=", product_id]
        ]
        product = await odoo.search_read(uid, "product.template",
                                         domain,
                                         limit=1)
        if product.get("error"):
            raise HTTPException(
                status_code=400, detail=product["error"]["message"])
        return ProductBase.from_odoo(product["result"][0])
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sincronize/product",
             summary="Sincronizar producto desde WooCommerce a Odoo")
async def sync_product_to_odoo(request: Request):
    """
    Recibe un webhook de WooCommerce cuando se actualiza un producto
    y lo sincroniza con Odoo
    """
    try:
        # Obtener headers del webhook
        webhook_headers = {
            "user_agent": request.headers.get("user-agent", ""),
            "content_type": request.headers.get("content-type", ""),
            "x_wc_webhook_source": request.headers.get(
                "x-wc-webhook-source", ""),
            "x_wc_webhook_topic": request.headers.get(
                "x-wc-webhook-topic", ""),
            "x_wc_webhook_resource": request.headers.get(
                "x-wc-webhook-resource", ""),
            "x_wc_webhook_event": request.headers.get(
                "x-wc-webhook-event", ""),
            "x_wc_webhook_signature": request.headers.get(
                "x-wc-webhook-signature", ""),
            "x_wc_webhook_id": request.headers.get("x-wc-webhook-id", ""),
            "x_wc_webhook_delivery_id": request.headers.get(
                "x-wc-webhook-delivery-id", "")
        }

        # Obtener el payload JSON del webhook
        webhook_payload = await request.json()

        # Log detallado para debugging
        _logger.info("=== WEBHOOK RECIBIDO ===")
        _logger.info("Headers: %s", webhook_headers)
        payload_str = json.dumps(webhook_payload, indent=2)
        _logger.info("Payload completo: %s", payload_str)

        # Extraer información del producto de WooCommerce
        if webhook_payload:
            product_data = {
                "wc_id": webhook_payload.get("id"),
                "name": webhook_payload.get("name"),
                "slug": webhook_payload.get("slug"),
                "sku": webhook_payload.get("sku"),
                "price": webhook_payload.get("price"),
                "regular_price": webhook_payload.get("regular_price"),
                "sale_price": webhook_payload.get("sale_price"),
                "description": webhook_payload.get("description"),
                "short_description": webhook_payload.get("short_description"),
                "categories": webhook_payload.get("categories", []),
                "images": webhook_payload.get("images", []),
                "status": webhook_payload.get("status"),
                "stock_quantity": webhook_payload.get("stock_quantity"),
                "manage_stock": webhook_payload.get("manage_stock"),
                "stock_status": webhook_payload.get("stock_status"),
                "weight": webhook_payload.get("weight"),
                "dimensions": webhook_payload.get("dimensions", {}),
                "attributes": webhook_payload.get("attributes", []),
                "date_created": webhook_payload.get("date_created"),
                "date_modified": webhook_payload.get("date_modified")
            }

            product_str = json.dumps(product_data, indent=2)
            _logger.info("Datos del producto extraídos: %s", product_str)

            # TODO: Implementar la lógica de sincronización con Odoo
            # Ejemplo:
            # odoo_client = OdooClient(...)
            # result = await odoo_client.create_or_update_product(product_data)

            success_msg = f"Producto {product_data['name']} procesado"
            return {
                "status": "success",
                "message": success_msg,
                "wc_product_id": product_data["wc_id"],
                "webhook_event": webhook_headers["x_wc_webhook_event"],
                "webhook_topic": webhook_headers["x_wc_webhook_topic"],
                "processed_data": product_data
            }
        else:
            _logger.warning("Payload vacío recibido")
            return {
                "status": "warning",
                "message": "Payload vacío recibido"
            }

    except json.JSONDecodeError as e:
        _logger.error(f"Error decodificando JSON del webhook: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        _logger.error(f"Error procesando webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/odoo", 
            summary="Consultar categorías en Odoo",
            response_model=List[CategoryBase])
async def get_odoo_categories(
    request: Request,
    name: Optional[str] = Query(
        None, description="Filtrar por nombre de categoría"),
    limit: int = Query(
        100, ge=1, le=500, description="Límite de categorías a retornar"),
    offset: int = Query(
        0, ge=0, description="Offset de categorías a retornar"),
    odoo: OdooClient = Depends(get_session_id),
):
    """
    Obtiene las categorías de productos desde Odoo
    
    Args:
        request: Request de FastAPI
        name: Nombre de categoría para filtrar (opcional)
        limit: Límite de resultados (máx 500)
        offset: Offset para paginación
        odoo: Cliente Odoo autenticado
        
    Returns:
        Lista de categorías de Odoo
    """
    try:
        # Autenticar con Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, 
                detail="No se pudo autenticar con Odoo")
        
        # Construir dominio de búsqueda
        domain = []
        if name:
            domain.append(["name", "ilike", name])
        
        # Consultar categorías desde Odoo
        categories = await odoo.search_read(
            uid,
            "product.category",
            domain=domain,
            fields=[
                "id", 
                "name", 
                "parent_id",
                "display_name",
                "complete_name"
            ],
            limit=limit,
            offset=offset
        )
        
        if categories.get("error"):
            error_msg = categories["error"].get("message", "Error desconocido")
            _logger.error(f"Error consultando categorías Odoo: {error_msg}")
            raise HTTPException(
                status_code=400, 
                detail=error_msg)
        
        # Convertir a CategoryBase
        category_list = [
            CategoryBase.from_odoo(category) 
            for category in categories["result"]
        ]
        
        _logger.info(f"Categorías obtenidas de Odoo: {len(category_list)}")
        return category_list
        
    except HTTPException as e:
        raise e
    except Exception as e:
        _logger.error(f"Error inesperado consultando categorías: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories/sync-from-odoo",
             summary="Sincronizar categorías desde Odoo a WooCommerce",
             response_model=CategorySyncResponse)
async def sync_categories_from_odoo(
    request: Request,
    sync_request: CategorySyncRequest = Body(
        default=CategorySyncRequest()),
    odoo: OdooClient = Depends(get_session_id),
):
    """
    Sincroniza categorías desde Odoo hacia WooCommerce
    
    Este endpoint:
    1. Lee las categorías desde Odoo usando el cliente autenticado
    2. Las transforma al formato de WooCommerce
    3. Las crea o actualiza en WooCommerce
    
    Args:
        request: Request de FastAPI
        sync_request: Parámetros de sincronización (IDs, límite, offset)
        odoo: Cliente Odoo autenticado mediante get_session_id
        
    Returns:
        Resultado de la sincronización con estadísticas
    """
    try:
        _logger.info("=== INICIANDO SINCRONIZACIÓN DE CATEGORÍAS ODOO -> WOOCOMMERCE ===")
        
        # Autenticar con Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, 
                detail="No se pudo autenticar con Odoo")
        
        _logger.info(f"Usuario Odoo autenticado: {uid}")
        
        # Construir dominio de búsqueda
        domain = []
        if sync_request.category_ids:
            domain.append(["id", "in", sync_request.category_ids])
            _logger.info(f"Filtrando categorías específicas: {sync_request.category_ids}")
        
        # Consultar categorías desde Odoo
        _logger.info(f"Consultando categorías Odoo (limit={sync_request.limit}, offset={sync_request.offset})")
        categories_response = await odoo.search_read(
            uid,
            "product.category",
            domain=domain,
            fields=[
                "id", 
                "name", 
                "parent_id",
                "display_name",
                "complete_name"
            ],
            limit=sync_request.limit,
            offset=sync_request.offset
        )
        
        if categories_response.get("error"):
            error_msg = categories_response["error"].get("message", "Error desconocido")
            _logger.error(f"Error consultando categorías Odoo: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        odoo_categories = categories_response.get("result", [])
        _logger.info(f"Categorías obtenidas de Odoo: {len(odoo_categories)}")
        
        # Convertir a CategoryBase
        category_list = [
            CategoryBase.from_odoo(category) 
            for category in odoo_categories
        ]
        
        # TODO: Implementar la sincronización con WooCommerce
        # Aquí puedes agregar la lógica para crear/actualizar en WooCommerce
        # Ejemplo:
        woocommerce_client = WooCommerceClient(...)
        for category in category_list:
            result = await woocommerce_client.create_or_update_category(category)
        
        # Por ahora, retornamos las categorías leídas
        categories_processed = len(category_list)
        
        response = CategorySyncResponse(
            status="success",
            message=f"Sincronización completada. {categories_processed} categorías procesadas.",
            categories_processed=categories_processed,
            categories_created=0,  # TODO: Implementar lógica WooCommerce
            categories_updated=0,  # TODO: Implementar lógica WooCommerce
            categories_failed=0,
            odoo_categories=category_list,
            errors=None
        )
        
        _logger.info(f"Sincronización completada: {categories_processed} categorías")
        _logger.info("=== FIN SINCRONIZACIÓN ===")
        
        return response
        
    except HTTPException as e:
        raise e
    except Exception as e:
        _logger.error(f"Error inesperado en sincronización: {e}")
        raise HTTPException(status_code=500, detail=str(e))

