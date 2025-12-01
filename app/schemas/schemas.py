
# Simple in-memory task store
from typing import List, Optional, Dict, Any

from pydantic import BaseModel


TASKS: Dict[str, Dict[str, Any]] = {}


class Product(BaseModel):
    id: int
    name: str
    sku: Optional[str]
    price: Optional[str]
    status: Optional[str]
    type: Optional[str]


class SyncResult(BaseModel):
    product_id: int
    synced: bool
    detail: Optional[str] = None


class BulkSyncRequest(BaseModel):
    product_ids: List[int]


class BulkSyncResponse(BaseModel):
    results: List[SyncResult]