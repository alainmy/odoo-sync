# --- Servicio para enviar PDF a webhook n8n ---
import json
from fastapi import APIRouter, Body, UploadFile, File, Header, HTTPException, status, Depends
import httpx
from app.core.config import settings
import logging

from app.services.odoo_service import get_moves
from app.schemas.invoice import OdooInvoiceSchema
_logger = logging.getLogger(__name__)
router = APIRouter()

# Configuración
# Cambia esta URL por la de tu webhook real
# http://localhost:5678/webhook-test/1df4c8cf-2fcf-452f-a851-27d74d4f3518
N8N_WEBHOOK_URL = settings.n8n_web_hook_url
# N8N_WEBHOOK_URL = "http://woocommerce_n8n:5678/webhook-test/1df4c8cf-2fcf-452f-a851-27d74d4f3518"
API_KEY = "supersecretkey"  # Cambia esto por tu clave real o usa variable de entorno


def api_key_auth(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")


@router.post("/send-invoice-pdf/", summary="Enviar PDF de factura a n8n", tags=["invoice"])
async def send_invoice_pdf(
        file: UploadFile = File(...),
        auth: None = Depends(api_key_auth)
):
    # Validar tipo de archivo
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400, detail="Solo se aceptan archivos PDF")

    # Leer el archivo
    file_bytes = await file.read()

    # Enviar a n8n webhook como multipart/form-data, simulando Postman
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                # No establecer Content-Type manualmente, httpx lo gestiona con 'files'
                "User-Agent": "PostmanRuntime/7.36.3"
            }
            response = await client.post(
                N8N_WEBHOOK_URL + "/1df4c8cf-2fcf-452f-a851-27d74d4f3518",
                headers=headers,
                timeout=60,
                files={"file": (file.filename, file_bytes, file.content_type)}
            )
            _logger.info(f"N8N response: {response.text}")
            response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=f"Error enviando a n8n: {str(e)}")

    return {"n8n_response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text}

# INteraccion con Chat en n8n
@router.post("/chatter/", summary="Enviar mensaje a chat en n8n", tags=["chatter"])
async def send_chat_message(
        message: str = None,
        auth: None = Depends(api_key_auth)
):
    # Validar tipo de archivo
    if not message:
        raise HTTPException(
            status_code=400, detail="Mensaje requerido")

    # Enviar a n8n webhook como multipart/form-data, simulando Postman
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                # No establecer Content-Type manualmente, httpx lo gestiona con 'files'
                "User-Agent": "PostmanRuntime/7.36.3"
            }
            response = await client.post(
                f"{N8N_WEBHOOK_URL}/87351f22-01b9-428e-ad05-e2b4894cea8d",
                headers=headers,
                data={"message": message},
                timeout=60
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502, detail=f"Error enviando a n8n: {str(response.text)}")
            else:
                _logger.info(f"N8N response: {response.text}")
                response_json = response.json()
                content = json.loads(response_json["message"]["content"])
                if content['function'] == 'get_moves':
                    moves = await get_moves(name=message)
                    return {"n8n_response": response_json, "moves": moves}
            _logger.info(f"N8N response: {response.text}")
            response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=f"Error enviando a n8n: {str(e)}")

    return {}