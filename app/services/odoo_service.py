

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
