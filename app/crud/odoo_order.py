

import datetime
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

    def cal_method(self, model, metod, params=None, context=None):
        """Llama a un método específico en Odoo."""
        if context:
            self.context.update(context)
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

    # create invoice
    def create_invoice(self, order_id,sale_journal_id=None):
        
        order = self.search_read_sync(
            "sale.order",
            domain=[["id", "=", order_id]],
            fields=["id", "name",
                    "partner_id",
                    "amount_total",
                    "order_line",
                    "reference",
                    "payment_term_id",
                    "fiscal_position_id"
                    ],
            limit=1,
            offset=0
        )
        logger.info(f"Order search result for invoice creation: {order}")
        if not order:
            logger.error(f"No se encontró la orden en Odoo para ID {order_id}")
            raise HTTPException(
                status_code=400, detail="No se encontró la orden en Odoo")
        order = order[0]
        logger.info(f"Order data for invoice creation: {order}")
        wizzard_id = self.create(
            model="sale.advance.payment.inv",
            vals={},
            context={
                'active_ids': [order_id],
                'active_model': 'sale.order',
                'active_id': order_id,
            }

        )
        if not wizzard_id or "result" not in wizzard_id:
            logger.error(f"Error creando wizzard de factura: {wizzard_id}")
            raise HTTPException(
                status_code=400, detail="Error creando wizzard de factura en Odoo")
        logger.info(f"Wizzard ID for invoice creation: {wizzard_id}")
        create_invoice = self.cal_method(
            "sale.advance.payment.inv",
            "create_invoices",
            params=[
                wizzard_id["result"]],
            context={
                'active_ids': [order_id],
                'active_model': 'sale.order',
                'active_id': order_id,
            }
        )
        logger.info(f"Invoice creation result: {create_invoice}")
        sale_ivoices_ids = self.search_read_sync(
            model="sale.order",
            domain=[
                ('id', '=', order_id)
            ],
            fields=['id', 'name', 'state', 'invoice_ids',],
            limit=1
        )
        if not sale_ivoices_ids:
            logger.error(f"No se encontró factura en Odoo")
            raise HTTPException(
                status_code=400, detail="No se encontró factura en Odoo")
        invoice_id = sale_ivoices_ids[0]['invoice_ids'][0]
        logger.info(f"Invoice ID for invoice creation: {invoice_id}")
        # Update invoice with sale journal
        if sale_journal_id:
            writed = self.write(
                model="account.move",
                vals={"journal_id": sale_journal_id},
                record_id=invoice_id
            )
        confirm_invoice = self.cal_method(
            'account.move',
            'action_post',
            params=[[invoice_id]]
        )
        return invoice_id, order
    
    def create_invoice_payment(self, invoice_id, order,
                               journal_id=None,
                               payment_method_title=None):
        
        payment_method_line_id= self.search_read_sync(
            model="account.payment.method.line",
            domain=[["code", "=", "manual"], ["journal_id", "=", journal_id]],
            fields=["id", "name","journal_id"],
            limit=1
        )
        if not payment_method_line_id:
            logger.error("No payment method found in Odoo")
            raise HTTPException(status_code=400, detail="No se encontró método de pago manual en Odoo")
        logger.info(f"Payment method line for invoice payment: {payment_method_line_id}")
        payment_wizard_id = self.create(
            model="account.payment.register",
            vals={
               "journal_id": journal_id,
                "partner_type": "customer",
                "payment_method_line_id": payment_method_line_id[0].get("id"),
                "amount": order.get("amount_total", 0),
                "communication": f"WC-{payment_method_title}",
                "payment_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            },
            context={
                'active_model': 'account.move',
                'active_ids': [invoice_id],
                'active_id': invoice_id,
            }
        )
        logger.info(f"Payment wizard ID for invoice payment: {payment_wizard_id}")
        if not payment_wizard_id or "result" not in payment_wizard_id:
            logger.error(f"Error creando wizzard de pago: {payment_wizard_id}")
            raise HTTPException(status_code=400, detail="Error creando wizzard de pago en Odoo")
        
        register_payment = self.cal_method(
            "account.payment.register",
            "action_create_payments",
            params=[payment_wizard_id["result"]],
            context={
                'active_model': 'account.move',
                'active_ids': [invoice_id],
                'active_id': invoice_id,
            }
        )
        logger.info(f"Payment registration result: {register_payment}")
        # get invoice payment
        invoice_payments = self.search_read_sync(
            model="account.move",
            domain=[["id", "=", invoice_id]],
            fields=["id", "name", "state","reconciled_payment_ids"],
            limit=1
        )
        if invoice_payments:
            if not invoice_payments[0].get("reconciled_payment_ids"):
                logger.error(f"No se encontró factura en Odoo")
                raise HTTPException(status_code=400, detail="No se encontró factura en Odoo")
            return invoice_payments[0]["reconciled_payment_ids"][0]
            