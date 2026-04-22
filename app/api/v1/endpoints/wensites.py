

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.api.v1.endpoints.odoo import get_odoo_from_active_instance
from app.crud.odoo import OdooClient
from app.schemas.websites import OodooConfig, Website, WebsiteListResponse, \
    WebsiteResponse
from app.crud import instance as crud_instance

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/from-active-instance", response_model=WebsiteListResponse)
async def read_websites(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
):

    uid = await odoo.odoo_authenticate()
    if not uid:
        raise HTTPException(
            status_code=401,
            detail="No se pudo autenticar con Odoo"
        )

    # Obtener lista de webs de Odoo
    websites = await odoo.search_read(
        uid,
        "website",
        domain=[["active", "=", True]],
        fields=["id", "name", "code"],
        limit=100
    )

    return WebsiteListResponse(
        total=len(websites["result"]),
        websites=[Website(**w) for w in websites["result"]]
    )


@router.post("/", response_model=WebsiteListResponse)
async def websites_from_odoo(
    request: Request,
    db: Session = Depends(get_db),
    odoo_config: OodooConfig = Body(None),
    current_user: Admin = Depends(get_current_user),
):

    if not odoo_config.url:
        active_instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        if not active_instance:
            logger.error(
                f"No active instance found for user {current_user.id}")
            return WebsiteListResponse(
                total=0,
                websites=[]
            )
        odoo_config = {
            "url": active_instance.odoo_url,
            "db": active_instance.odoo_db,
            "username": active_instance.odoo_username,
            "password": active_instance.odoo_password
        }
    odoo = OdooClient(**odoo_config.model_dump())
    try:
        uid = await odoo.odoo_authenticate()
        if not uid:
            logger.error(f"Failed to authenticate with Odoo: {uid}")
            return WebsiteListResponse(
                total=0,
                websites=[]
            )

        # Obtener lista de webs de Odoo
        websites = await odoo.search_read(
            uid,
            "website",
            domain=[],
            fields=["id", "name"],
            limit=100
        )

        return WebsiteListResponse(
            total=len(websites["result"]),
            websites=[Website(**w) for w in websites["result"]]
        )
    except Exception as e:
        logger.error(f"Error fetching websites from Odoo: {e}")
        return WebsiteListResponse(
            total=0,
            websites=[]
        )


@router.get("/odoo-websites/{website_id}", response_model=WebsiteResponse)
async def read_wensite(
    website_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
):

    uid = await odoo.odoo_authenticate()
    if not uid:
        raise HTTPException(
            status_code=401,
            detail="No se pudo autenticar con Odoo"
        )

    # Obtener lista de webs de Odoo
    website = await odoo.search_read(
        uid,
        "website",
        domain=[["id", "=", website_id]],
        fields=["id", "name", "code"],
        limit=1
    )

    return WebsiteResponse(
        website=Website(**website["result"][0])
    )
