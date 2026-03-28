

import json
import os
import dotenv
from fastapi import HTTPException
import requests
import logging

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


ODOO_URL = "http://host.docker.internal:8069"
ODOO_DB = "c4e"
ODOO_USERNAME = "admin"
ODOO_PASSWORD = "admin"


class OdooClient:

    url = None
    db = None
    username = None
    password = None
    context = {
        "lang": "en_US",
        "tz": "America/Havana",
        "website_id": 1,
        "allowed_company_ids": [1],
        "uid": 2
    }
    uid = 2

    def __init__(self, url=None, db=None,
                 username=None,
                 password=None,
                 context={}):
        self.url = url if url else ODOO_URL
        self.db = db if db else ODOO_DB
        self.username = username if username else ODOO_USERNAME
        self.password = password if password else ODOO_PASSWORD
        self.context = context if context else self.context

    def web_authentication(self, base_url):

        response = requests.post(
            f'{base_url}/web/session/authenticate',
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"db": self.db, "login": self.username, "password": self.password}
            }
        )
        return response

    async def odoo_authenticate(self):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "login",
                "args": [
                    self.db if self.db else ODOO_DB,
                    self.username if self.username else ODOO_USERNAME,
                    self.password if self.password else ODOO_PASSWORD
                ]
            },
        }
        try:
            response = requests.post(f"{self.url}/jsonrpc", json=payload)
            result = response.json()
            logger.info(f"Odoo authentication response: {result}")
            if result.get("error"):
                logger.error(f"Odoo authentication error: {result['error']}")
                raise HTTPException(status_code=500,
                                    detail=str(result["error"]))
            self.uid = result["result"]
            return result["result"]
        except Exception as e:
            logger.error(f"Error authenticating to Odoo: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def search_read(self,
                          uid,
                          model,
                          domain=None,
                          fields=None,
                          limit=100,
                          offset=0):
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
                    "search_read",
                    [domain or []],
                    {
                        "fields": fields or ["id", "name", "list_price",
                                             "description", "image_1920"],
                        "offset": limit * offset,
                        "limit": limit,
                        "order": "id asc",
                        "context": self.context
                    }
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
                logger.error(f"Odoo search_read error: {result['error']}")
                raise HTTPException(status_code=500,
                                    detail=str(result["error"]))
            logger.info(f"Odoo search_read response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in search_read: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def search_read_sync(self,
                         model,
                         domain=None,
                         fields=None,
                         limit=100,
                         offset=0,
                         order="id asc"):
        """Versión síncrona de search_read para usar en contextos no async."""
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
                    "search_read",
                    [domain or []],
                    {
                        "fields": fields or ["id", "name", "list_price",
                                             "description", "image_1920"],
                        "offset": limit * offset,
                        "limit": limit,
                        "order": order,
                        "context": self.context
                    }
                ],
            },
            "id": 2
        }
        response = requests.post(f"{self.url}/jsonrpc", json=payload)
        result = response.json()
        return result.get("result", [])

    def create(self, uid=None, model=None, vals=None):
        """Crea un registro en Odoo para el modelo y valores dados."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db,
                    self.uid if not uid else uid,
                    self.password,
                    model,
                    "create",
                    [vals],
                    {"context": self.context}
                ],
            },
            "id": 3
        }
        response = requests.post(f"{self.url}/jsonrpc", json=payload)
        result = response.json()
        if "result" in result:
            return result  # Devuelve el ID del nuevo registro
        else:
            raise Exception(f"Odoo create error: {result}")

    def write(self, model, vals, record_id):
        """Escribe datos en un registro existente en Odoo."""
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
                    "write",
                    [record_id, vals],
                    {"context": self.context}
                ],
            },
            "id": 3
        }
        try:
            response = requests.post(f"{self.url}/jsonrpc", json=payload)
            result = response.json()
            if result.get("error"):
                logger.error(f"Odoo write error: {result['error']}")
                raise HTTPException(status_code=500,
                                    detail=str(result["error"]))
            logger.info(f"Odoo write response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in write: {str(e)}")
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
