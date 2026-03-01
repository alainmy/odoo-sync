

from typing import Optional

from fastapi import HTTPException, Query

from app.crud.odoo import OdooClient


async def get_moves(
    name: Optional[str] = Query(
        None, description="Filtrar por nombre de producto"),
    limit: int = Query(
        100, ge=1, le=100, description="Limite de productos a retornar"),
    offset: int = Query(
        0, ge=0,
        description="Offset de productos a retornar")):
    try:
        odoo = OdooClient()
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="No se pudo autenticar")
        domain = []
        if name:
            domain.append(["name", "ilike", name])
        moves = await odoo.search_read(uid,
                                       "account.move",
                                       domain=domain,
                                       limit=limit,
                                       fields=[
                                           "id",
                                           "partner_id",
                                       ],
                                       offset=offset)
        if moves.get("error"):
            raise HTTPException(
                status_code=400, detail=moves["error"]["message"])
        return moves["result"]
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def create_customer_in_odoo(customer_data: dict,
                            odoo_client: OdooClient = None) -> dict:
    """
    Crea un cliente en Odoo utilizando la API XML-RPC.

    Args:
        customer_data: Diccionario con los datos del cliente a crear. 
                       Debe contener al menos 'name' y 'email'.

    Returns:
        Diccionario con el resultado de la operación de creación del cliente en Odoo.
    """
    try:
        odoo = odoo_client if odoo_client else OdooClient()
        uid = odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401, detail="No se pudo autenticar con Odoo")

        # Preparar los datos del cliente para Odoo

        # Crear el cliente en Odoo
        result = odoo.create(uid, 'res.partner', customer_data)

        if result.get("error"):
            raise HTTPException(
                status_code=400, detail=result["error"]["message"])

        return result["result"]

    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
