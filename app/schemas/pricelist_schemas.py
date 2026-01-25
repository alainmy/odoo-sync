"""Pydantic schemas for pricelist operations."""

from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from datetime import datetime


class PricelistSyncBase(BaseModel):
    """Base schema for pricelist sync."""
    odoo_pricelist_id: int = Field(..., description="Odoo pricelist ID")
    odoo_pricelist_name: Optional[str] = Field(None, description="Odoo pricelist name")
    instance_id: int = Field(..., description="WooCommerce instance ID")
    active: bool = Field(True, description="Is this pricelist active for sync")
    price_type: Literal['regular', 'sale', 'meta'] = Field('regular', description="Price type")
    meta_key: Optional[str] = Field(None, description="Meta key for custom price fields")


class PricelistSyncCreate(PricelistSyncBase):
    """Schema for creating a new pricelist sync."""
    pass


class PricelistSyncUpdate(BaseModel):
    """Schema for updating a pricelist sync."""
    odoo_pricelist_name: Optional[str] = None
    active: Optional[bool] = None
    price_type: Optional[Literal['regular', 'sale', 'meta']] = None
    meta_key: Optional[str] = None
    message: Optional[str] = None


class PricelistSyncResponse(PricelistSyncBase):
    """Schema for pricelist sync response."""
    id: int
    last_synced_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    message: Optional[str]
    
    class Config:
        from_attributes = True


class OdooPricelist(BaseModel):
    """Schema for Odoo pricelist data."""
    id: int
    name: str
    active: bool
    currency_id: Optional[List] = None  # [id, name]
    
    
class OdooPricelistItem(BaseModel):
    """Schema for Odoo pricelist item data."""
    id: int
    pricelist_id: list  # [id, name]
    product_tmpl_id: Optional[list] = None  # [id, name]
    product_id: Optional[list] = None  # [id, name]
    fixed_price: Optional[float] = None
    percent_price: Optional[float] = None
    compute_price: str = Field(..., description="fixed, percentage, formula")
    base: str = Field(..., description="list_price, standard_price, pricelist")


class ProductPriceUpdate(BaseModel):
    """Schema for product price update request."""
    odoo_product_id: int = Field(..., description="Odoo product ID")
    instance_id: int = Field(..., description="WooCommerce instance ID")
    pricelist_id: Optional[int] = Field(None, description="Specific pricelist ID, None = all active")


class PriceSyncResult(BaseModel):
    """Schema for price sync result."""
    odoo_product_id: int
    woocommerce_id: Optional[int]
    success: bool
    synced_prices: dict = Field(default_factory=dict, description="Synced prices by type")
    message: str
    error_details: Optional[str] = None


class BulkPriceSyncRequest(BaseModel):
    """Schema for bulk price sync request."""
    instance_id: int = Field(..., description="WooCommerce instance ID")
    pricelist_id: Optional[int] = Field(None, description="Specific pricelist ID, None = all active")
    product_ids: Optional[List[int]] = Field(None, description="Specific product IDs, None = all synced products")


class BulkPriceSyncResponse(BaseModel):
    """Schema for bulk price sync response."""
    total_products: int
    successful: int
    failed: int
    results: List[PriceSyncResult]
