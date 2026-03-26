

import json
import os
import dotenv
from fastapi import HTTPException
import requests
import logging

from app.crud.odoo import OdooClient

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


ODOO_URL = "http://host.docker.internal:8069"
ODOO_DB = "c4e"
ODOO_USERNAME = "admin"
ODOO_PASSWORD = "admin"


class OrderClient(OdooClient):

    def message_post(self, model, record_id, body, **kwargs):
        """Envía un mensaje a un registro en Odoo."""
        # Preparar los parámetros del mensaje
        message_params = {
            'body': body,
            'message_type': kwargs.get('message_type', 'comment'),
        }

        # Agregar otros parámetros opcionales
        if 'subtype_xmlid' in kwargs:
            message_params['subtype_xmlid'] = kwargs['subtype_xmlid']
        if 'partner_ids' in kwargs:
            message_params['partner_ids'] = kwargs['partner_ids']
        if 'subject' in kwargs:
            message_params['subject'] = kwargs['subject']

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    "message_post",
                    [record_id],  # Solo el ID del registro
                    message_params  # Los parámetros del mensaje como kwargs
                ],
            },
            "id": 4
        }

        try:
            response = requests.post(f"{self.url}/jsonrpc", json=payload)
            result = response.json()
            if result.get("error"):
                logger.error(f"Odoo message_post error: {result['error']}")
                raise HTTPException(
                    status_code=500, detail=str(result["error"]))
            logger.info(f"Odoo message_post response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in message_post: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def cal_method(self, model, metod, params=None):
        """Llama a un método específico en Odoo."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db,
                    self.uid,
                    self.password,
                    model,
                    metod,
                    params or [],
                    {"context": self.context}
                ],
            },
            "id": 4
        }
        try:
            response = requests.post(f"{self.url}/jsonrpc", json=payload)
            result = response.json()
            if result.get("error"):
                logger.error(f"Odoo cal_method error: {result['error']}")
                raise HTTPException(status_code=500,
                                    detail=str(result["error"]))
            logger.info(f"Odoo cal_method response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in cal_method: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def search_count(self, uid, model, domain):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db,
                    uid,
                    self.password,
                    model,
                    "search_count",
                    [domain],
                    {"context": self.context}
                ],
            },
            "id": 2
        }
        headers = {"Cookie": f"session_id={1}"}
        try:
            response = requests.post(f"{self.url}/jsonrpc",
                                     json=payload, headers=headers)
            result = response.json()
            if result.get("error"):
                logger.error(f"Odoo search_count error: {result['error']}")
                raise HTTPException(status_code=500,
                                    detail=str(result["error"]))
            logger.info(f"Odoo search_count response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in search_count: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
