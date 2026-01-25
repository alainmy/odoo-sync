from ast import Param
from datetime import datetime, date
from email import message
from http import client
import time
from app.session import create_session, get_session
from app.schemas.products import OdooProductSchema, ProductBase
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
from app.schemas.invoice import OdooInvoiceSchema
from app.telegram_bot import application as app
from app.crud import instance as crud_instance
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.db.session import get_db
from sqlalchemy.orm import Session
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
    api_session = request.headers.get(
        "api-session") or request.headers.get("api_session") or "default-session"
    
    session = await get_session(api_session)
    if session:
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


async def get_odoo_from_active_instance(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Obtener cliente de Odoo desde la instancia activa del usuario"""
    # Obtener instancia activa
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa configurada. Por favor activa una instancia primero."
        )
    
    # Obtener sesión si existe
    api_session = request.headers.get("api-session") or request.headers.get("api_session") or "default-session"
    session = await get_session(api_session)
    
    context = default_context.copy()
    context.update({
        "lang": request.headers.get("lang", "en_US"),
        "tz": request.headers.get("tz", "America/Havana"),
        "website_id": request.headers.get("website_id", 1),
    })
    
    if session:
        session_data = json.loads(session)
        if "context" in session_data:
            context.update(session_data["context"])
    
    # Crear cliente con configuraciones de la instancia activa
    odoo = OdooClient(
        url=instance.odoo_url,
        db=instance.odoo_db,
        username=instance.odoo_username,
        password=instance.odoo_password,
        context=context
    )
    
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
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
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
                                              "id",
                                              "name",
                                              "list_price",
                                              "description",
                                              "image_1920",
                                              "categ_id",
                                              "sale_ok",
                                              "uom_id",
                                              "uom_po_id",
                                              "uom_category_id",
                                              "weight",
                                              "weight_uom_name",
                                              "volume",
                                              "volume_uom_name",
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
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    try:
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="Invalid Credentials")
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


@router.get("/products", response_model=List[OdooProductSchema])
async def get_products(
    request: Request,
    name: Optional[str] = Query(
        None, description="Filtrar por nombre de producto"),
    limit: int = Query(
        100, ge=1, le=100, description="Limite de productos a retornar"),
    offset: int = Query(
        0, ge=0,
        description="Offset de productos a retornar"),
    odoo: OdooClient = Depends(get_session_id),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    try:
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="Invalid Credentials")
        domain = []
        if name:
            domain.append(["name", "ilike", name])
        products = await odoo.search_read(
            uid,
            "product.template",
            domain=domain,
            limit=limit,
            fields=[
                "id",
                "name",
                "default_code",
                "list_price",
                "standard_price",
                "description",
                "description_sale",
                "categ_id",
                "product_tag_ids",
                "active",
                "sale_ok",
                "purchase_ok",
                "type",
                "qty_available",
                "virtual_available",
                "weight",
                "volume",
                "image_1920",
                "create_date",
                "write_date"
            ],
            offset=offset
        )
        if products.get("error"):
            raise HTTPException(
                status_code=400, detail=products["error"]["message"])
        return [OdooProductSchema.from_odoo(product) for product in products["result"]]
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sincronize/product",
             summary="Sincronizar producto desde WooCommerce a Odoo")
async def sync_product_to_odoo(request: Request):
    """
    Webhook endpoint: Receives WooCommerce product updates and queues them for sync to Odoo.
    Now uses Celery for async processing with idempotency.
    """
    try:
        from app.tasks.webhook_tasks import process_webhook

        # Get webhook headers
        webhook_headers = {
            "user_agent": request.headers.get("user-agent", ""),
            "content_type": request.headers.get("content-type", ""),
            "x_wc_webhook_source": request.headers.get("x-wc-webhook-source", ""),
            "x_wc_webhook_topic": request.headers.get("x-wc-webhook-topic", ""),
            "x_wc_webhook_resource": request.headers.get("x-wc-webhook-resource", ""),
            "x_wc_webhook_event": request.headers.get("x-wc-webhook-event", ""),
            "x_wc_webhook_signature": request.headers.get("x-wc-webhook-signature", ""),
            "x_wc_webhook_id": request.headers.get("x-wc-webhook-id", ""),
            "x_wc_webhook_delivery_id": request.headers.get("x-wc-webhook-delivery-id", "")
        }

        # Get webhook payload
        webhook_payload = await request.json()

        # Log for debugging
        _logger.info("=== WEBHOOK RECEIVED ===")
        _logger.info("Topic: %s, Event: %s",
                    webhook_headers["x_wc_webhook_topic"],
                    webhook_headers["x_wc_webhook_event"])
        _logger.info("Product ID: %s", webhook_payload.get("id"))

        # Validate webhook signature (ENABLED for production security)
        signature = webhook_headers.get("x_wc_webhook_signature", "")
        if signature:
            from app.tasks.webhook_tasks import validate_webhook_signature
            body = await request.body()
            if not validate_webhook_signature(body, signature, settings.wc_webhook_secret):
                _logger.warning(f"Invalid webhook signature for event {webhook_headers.get('x_wc_webhook_delivery_id')}")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            _logger.warning(f"No webhook signature provided for event {webhook_headers.get('x_wc_webhook_delivery_id')}")

        # Build event type
        topic = webhook_headers.get("x_wc_webhook_topic", "unknown")
        event = webhook_headers.get("x_wc_webhook_event", "unknown")
        event_type = f"{topic.replace('.', '_')}_{event}".lower()

        # Generate unique event ID
        webhook_id = webhook_headers.get("x_wc_webhook_delivery_id") or \
                     f"{event_type}_{webhook_payload.get('id')}_{int(time.time())}"

        # Queue webhook processing task with Celery
        task = process_webhook.apply_async(
            args=[event_type, webhook_payload, webhook_id],
            retry=True
        )

        _logger.info(f"Webhook queued for processing. Task ID: {task.id}")

        return {
            "status": "queued",
            "message": f"Webhook queued for async processing",
            "task_id": task.id,
            "event_id": webhook_id,
            "wc_product_id": webhook_payload.get("id"),
            "webhook_event": event,
            "webhook_topic": topic
        }

    except Exception as e:
        _logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
                detail="Invalid Credentials")

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
        _logger.info(
            "=== INICIANDO SINCRONIZACIÓN DE CATEGORÍAS ODOO -> WOOCOMMERCE ===")

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
            _logger.info(
                f"Filtrando categorías específicas: {sync_request.category_ids}")

        # Consultar categorías desde Odoo
        _logger.info(
            f"Consultando categorías Odoo (limit={sync_request.limit}, offset={sync_request.offset})")
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
            error_msg = categories_response["error"].get(
                "message", "Error desconocido")
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

        _logger.info(
            f"Sincronización completada: {categories_processed} categorías")
        _logger.info("=== FIN SINCRONIZACIÓN ===")

        return response

    except HTTPException as e:
        raise e
    except Exception as e:
        _logger.error(f"Error inesperado en sincronización: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-invoice/", summary="Guardar factura en Odoo", tags=["invoice"])
async def save_invoice(
        request: Request,
        data: OdooInvoiceSchema = Body(...),
        odoo: OdooClient = Depends(get_session_id),
):

    chat_id = request.headers.get("chat-id", None)
    private_chat_id = request.headers.get("private-chat-id", None)
    username = request.headers.get("username", None)
    try:
        # Autenticar con Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="No se pudo autenticar con Odoo")

        # Crear factura en Odoo
        _logger.info(f"Creando factura en Odoo (uid={uid})")
        vals = data.model_dump()
        reference = vals.pop("invoice_reference")
        vals.update({"name": reference})

        # Search partner by email
        partner = vals.pop("client")
        partner.pop("address")

        vals["partner_id"] = partner
        partner = await odoo.search_read(
            uid,
            "res.partner",
            domain=[["vat", "=", partner.get("vat")]],
            fields=["id", "name", "vat"],
            limit=1,
            offset=0
        )
        if not partner.get("result"):
            _logger.warning(
                f"No se encontró cliente con VAT {partner.get('vat')}")
            raise HTTPException(
                status_code=400,
                detail="No se encontró cliente con VAT")
        vals["partner_id"] = partner["result"][0]["id"]
        lines = vals.pop("line_ids")

        # Get companys
        company = await odoo.search_read(
            uid,
            "res.company",
            domain=[["vat", "=", partner.get("vat")]],
            fields=["id", "name", "account_journal_suspense_account_id"],
            limit=1,
            offset=0
        )
        if not company.get("result"):
            _logger.warning(
                f"No se encontró empresa con VAT {partner.get('vat')}")
            raise HTTPException(
                status_code=400,
                detail="No se encontró empresa con VAT")

        for line in lines:
            product = await odoo.search_read(
                uid,
                "product.product",
                domain=[["default_code", "=", line.get("product_code")]],
                fields=["id", "name", "list_price", "uom_id",
                        "uom_po_id", "uom_category_id"],
                limit=1,
                offset=0
            )
            if not product.get("result"):
                _logger.warning(
                    f"No se encontró producto con código {line.get('product_code')}")
                continue
            line["product_id"] = product["result"][0]["id"]
            line["price_unit"] = product["result"][0]["list_price"]
            line["quantity"] = line.pop("quantity")
            line["account_id"] = company["result"][0]["account_journal_suspense_account_id"][0]
            # line.pop("taxes")

        invoice_date = datetime.strptime(
            vals["invoice_date"], "%d/%m/%Y")
        invoice_date_due = datetime.strptime(
            vals["invoice_date_due"], "%d/%m/%Y")
        vals['invoice_line_ids'] = [(0, 0, line) for line in lines]
        vals["invoice_date"] = invoice_date.strftime("%Y-%m-%d")
        vals["invoice_date_due"] = invoice_date_due.strftime("%Y-%m-%d")
        vals["move_type"] = "out_invoice"

        invoice = odoo.create('account.move', vals)
        # recuperar factura
        invoice = await odoo.search_read(
            uid,
            "account.move",
            domain=[
                ["id", "=", invoice['result']]],
            fields=["id", "name",],
            limit=1, offset=0)
        invoice_resut = invoice['result'][0]

        if private_chat_id:
            message_text = f"username: {username}\n📥 Factura creada: {invoice_resut['name']}"
            await app.bot.send_message(chat_id=private_chat_id, text=message_text)
        if chat_id:
            message_text = f"username: {username}\n📥 Factura creada:  {invoice_resut['name']}"
            await app.bot.send_message(chat_id=chat_id, text=message_text)
        if invoice.get("error"):
            error_msg = invoice["error"].get("message", "Error desconocido")
            _logger.error(f"Error creando factura en Odoo: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException as e:
        raise e
    except Exception as e:
        _logger.error(f"Error inesperado creando factura: {e}")
        msg = f"Error inesperado creando factura. Por favor contacta con el administrador del bot."
        if private_chat_id:
            await app.bot.send_message(chat_id=private_chat_id, text=msg)
        if chat_id:
            await app.bot.send_message(chat_id=chat_id, text=msg)
        raise HTTPException(status_code=500, detail=str(e))

    return {"odoo_invoice_id": invoice["result"]}
