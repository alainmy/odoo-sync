

from typing import List, Optional

from pydantic import BaseModel


class DeliverySchema(BaseModel):

    id: int
    name: str
    fixed_price: Optional[float] = None
    amount: Optional[float] = None
    free_over: Optional[bool] = None
    product_id: Optional[list] = None
    country_ids: Optional[list] = []
    state_ids: Optional[list] = []


class OdooDeliveryListResponse(BaseModel):
    """Response with Odoo products and sync status"""
    total_count: int
    delivery_methods: List[DeliverySchema]
    filters_applied: Optional[dict] = None
