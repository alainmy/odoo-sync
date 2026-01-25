"""
Tag sync repository.

Handles all tag synchronization database operations.
"""
from sqlalchemy.orm import Session
from app.models.admin import TagSync
from app.repositories.base_sync_repository import BaseSyncRepository


class TagSyncRepository(BaseSyncRepository[TagSync]):
    """
    Repository for tag sync operations.
    
    Inherits all CRUD operations from BaseSyncRepository.
    Add tag-specific methods here if needed.
    """
    
    model_class = TagSync
