from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime

from app.schemas import language


class WooCommerceInstanceBase(BaseModel):
    name: str
    woocommerce_url: str
    woocommerce_consumer_key: str
    woocommerce_consumer_secret: str
    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_password: str
    is_active: bool = False
    odoo_language: Optional[str] = "en_US"


class WooCommerceInstanceCreate(WooCommerceInstanceBase):
    pass


class WooCommerceInstanceUpdate(BaseModel):
    name: Optional[str] = None
    woocommerce_url: Optional[str] = None
    woocommerce_consumer_key: Optional[str] = None
    woocommerce_consumer_secret: Optional[str] = None
    odoo_url: Optional[str] = None
    odoo_db: Optional[str] = None
    odoo_username: Optional[str] = None
    odoo_password: Optional[str] = None
    is_active: Optional[bool] = None
    odoo_language: Optional[str] = None


class WooCommerceInstance(WooCommerceInstanceBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
