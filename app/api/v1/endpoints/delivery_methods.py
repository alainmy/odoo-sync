
import logging
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.endpoints.odoo import get_odoo_from_active_instance
from app.crud.odoo import OdooClient
from app.db.session import get_db
from app.schemas.delivery import DeliverySchema, OdooDeliveryListResponse

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/delivery-methods")


@router.get("/", response_model=OdooDeliveryListResponse)
async def delivery_methods(
    request: Request,
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    limit: int = Query(
        50, le=200, description="Number of delivery methods to return"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
        filter_status: Optional[str] = Query(
            None,
            description="Filter by sync status: never_synced, synced, error"
    ), search: Optional[str] = Query(
        None, description="Search by delivery method name"),
        db: Session = Depends(get_db),
):

    uid = await odoo.odoo_authenticate()
    domain = []
    if search:
        domain.append(["name", "ilike", search])

    logger.info(
        f"Fetching delivery methods from Odoo: domain={domain}, limit={limit}")

    search_count = await odoo.search_count(uid, "delivery.carrier",
                                           domain=domain)
    deliveries_count = search_count["result"]
    delivery_methods_result = await odoo.search_read(
        uid=uid,
        model="delivery.carrier",
        domain=domain,
        limit=limit,
        offset=offset,
        fields=[
            "id",
            "name",
            "fixed_price",
            "free_over",
            "amount",
            "product_id",
            "country_ids",
            "state_ids"
        ]
    )

    return OdooDeliveryListResponse(
        total_count=deliveries_count,
        delivery_methods=[
            DeliverySchema(
                id=item["id"],
                name=item["name"],
                fixed_price=item["fixed_price"],
                amount=item["amount"],
                free_over=item["free_over"],
                product_id=item["product_id"],
                country_ids=item["country_ids"],
                state_ids=item["state_ids"],
            ) for item in delivery_methods_result["result"]
        ]
    )
