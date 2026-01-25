"""
Schemas for sync management
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from decimal import Decimal


class OdooProductWithSyncStatus(BaseModel):
    """Odoo product with sync status information"""
    # Odoo product data
    id: int
    name: str
    default_code: Optional[str] = None  # SKU
    list_price: Optional[float] = None
    write_date: Optional[str] = None  # Odoo modification date
    
    # Sync status
    sync_status: str = Field(..., description="never_synced, synced, modified, error")
    woocommerce_id: Optional[int] = None
    last_synced_at: Optional[datetime] = None
    sync_date: Optional[datetime] = None
    odoo_write_date: Optional[datetime] = None
    published: bool = False
    needs_sync: bool = False
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class SyncStatusEnum(str):
    NEVER_SYNCED = "never_synced"
    SYNCED = "synced"
    MODIFIED = "modified"
    ERROR = "error"


class ProductSyncStatusResponse(BaseModel):
    """Response with product and its sync status"""
    odoo_id: int
    name: str
    sku: Optional[str] = None
    price: Optional[float] = None
    odoo_write_date: Optional[datetime] = None
    
    # Sync information
    sync_status: str
    woocommerce_id: Optional[int] = None
    name: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    needs_sync: bool = False
    published: bool = False
    
    # Error details
    has_error: bool = False
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class BatchSyncRequest(BaseModel):
    """Request to sync multiple products"""
    odoo_ids: List[int] = Field(..., min_items=1, description="List of Odoo product IDs to sync")
    force_sync: bool = Field(default=False, description="Force sync even if already synced")
    create_if_not_exists: bool = Field(default=True, description="Create in WooCommerce if doesn't exist")
    update_existing: bool = Field(default=True, description="Update existing WooCommerce products")


class BatchSyncResponse(BaseModel):
    """Response for batch sync operation"""
    task_id: Optional[str] = None
    status: str
    total_products: int
    message: str
    results: Optional[List[dict]] = None


class SyncQueueItem(BaseModel):
    """Item in the sync queue"""
    odoo_id: int
    name: str
    sku: Optional[str] = None
    odoo_write_date: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    reason: str = Field(..., description="never_synced, modified, error_retry")
    priority: int = Field(default=5, ge=1, le=10)
    
    class Config:
        from_attributes = True


class SyncQueueResponse(BaseModel):
    """Response with sync queue"""
    total_count: int
    products: List[SyncQueueItem]


class DetectChangesRequest(BaseModel):
    """Request to detect changes in Odoo products"""
    since: Optional[datetime] = None
    limit: int = Field(default=100, le=500)
    only_modified: bool = Field(default=True, description="Only products modified after last sync")


class DetectChangesResponse(BaseModel):
    """Response with detected changes"""
    total_modified: int
    products: List[ProductSyncStatusResponse]
    

class OdooProductListRequest(BaseModel):
    """Request to list Odoo products with sync status"""
    limit: int = Field(default=50, le=200)
    offset: int = Field(default=0, ge=0)
    filter_status: Optional[str] = Field(None, description="never_synced, modified, synced, error")
    search: Optional[str] = None  # Search by name or SKU
    category_id: Optional[int] = None


class OdooProductListResponse(BaseModel):
    """Response with Odoo products and sync status"""
    total_count: int
    products: List[ProductSyncStatusResponse]
    filters_applied: dict


class SyncStatisticsResponse(BaseModel):
    """Statistics about sync status"""
    total_products: int
    never_synced: int
    synced: int
    modified: int
    errors: int
    last_sync: Optional[datetime] = None
