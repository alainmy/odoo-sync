

import json
import os
import dotenv
import requests
import logging
dotenv.load_dotenv()

__logger = logging.getLogger(__name__)
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

    def __init__(self, url=ODOO_URL, db=ODOO_DB,
                 username=ODOO_USERNAME,
                 password=ODOO_PASSWORD,
                 context={}):
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.context = context if context else self.context

    async def odoo_authenticate(self):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "login",
                "args": [
                    os.environ.get("ODOO_DB"),
                    self.username,
                    self.password
                ]
            },
        }
        try:
            response = requests.post(f"{self.url}/jsonrpc", json=payload)
            result = response.json()
            __logger.info(f"Odoo authentication response: {result}")
            if "error" in result:
                return None
            self.uid = result["result"]
            return result["result"]
        except Exception as e:
            __logger.error(f"Error authenticating to Odoo: {str(e)}")
            return None

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
        base_url = os.environ.get("ODOO_URL")
        headers = {"Cookie": f"session_id={1}"}
        response = requests.post(f"{base_url}/jsonrpc",
                                 json=payload, headers=headers)
        result = response.json()
        return result

    def search_read_sync(self,
                         model,
                         domain=None,
                         fields=None,
                         limit=100,
                         offset=0):
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
                        "order": "id asc",
                        "context": self.context
                    }
                ],
            },
            "id": 2
        }
        response = requests.post(f"{self.url}/jsonrpc", json=payload)
        result = response.json()
        return result.get("result", [])

    def create(self, model, vals):
        """Crea un registro en Odoo para el modelo y valores dados."""
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
