from app.db.base import Base
from pydantic import BaseModel, Field
from typing import Optional


# --- ProductSync Schemas ---
class ProductSyncBase(BaseModel):
    odoo_id: int
    woocommerce_id: int
    created: Optional[bool] = None
    updated: Optional[bool] = None
    skipped: Optional[bool] = None
    error: Optional[bool] = None
    message: Optional[str] = None
    error_details: Optional[str] = None


class ProductSyncCreate(ProductSyncBase):
    pass


class ProductSync(ProductSyncBase):
    id: int
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: str
    error_details: str


class AdminBase(BaseModel):
    name: str
    description: str


class AdminCreate(AdminBase):
    pass


class Admin(AdminBase):
    id: int

    class Config:
        from_attributes = True


class CategorySyncBase(BaseModel):
    odoo_id: int
    woocommerce_id: int
    created: Optional[bool] = None
    updated: Optional[bool] = None
    skipped: Optional[bool] = None
    error: Optional[bool] = None
    message: Optional[str] = None
    error_details: Optional[str] = None


class CategorySyncCreate(CategorySyncBase):
    pass


class CategorySync(CategorySyncBase):
    id: int
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: str
    error_details: str