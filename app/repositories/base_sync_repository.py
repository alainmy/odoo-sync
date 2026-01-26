"""
Base repository for sync operations.

Provides generic CRUD operations for sync models (Product, Category, Tag).
Eliminates code duplication by implementing common patterns once.
"""
from typing import TypeVar, Generic, Optional, List, Dict, Type
from sqlalchemy.orm import Session
from app.models.admin import ProductSync, CategorySync, TagSync

# Generic type for sync models
T = TypeVar('T', ProductSync, CategorySync, TagSync)


class BaseSyncRepository(Generic[T]):
    """
    Base repository providing common CRUD operations for sync models.
    
    Subclasses must define:
        - model_class: The SQLAlchemy model class
        
    Example:
        class ProductSyncRepository(BaseSyncRepository[ProductSync]):
            model_class = ProductSync
    """
    
    model_class: Type[T] = None  # Must be set by subclass
    
    def __init__(self, db: Session):
        """
        Initialize repository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        if self.model_class is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define model_class attribute"
            )
    
    def create_sync(
        self,
        odoo_id: int,
        woocommerce_id: int,
        instance_id: int,
        odoo_name: str = "",
        created: bool = False,
        updated: bool = False,
        skipped: bool = False,
        error: bool = False,
        message: str = "",
        error_details: str = ""
    ) -> T:
        """
        Create a new sync record.
        
        Args:
            odoo_id: Odoo entity ID
            woocommerce_id: WooCommerce entity ID
            instance_id: WooCommerce instance ID
            odoo_name: Odoo entity name
            created: Whether entity was created in WooCommerce
            updated: Whether entity was updated in WooCommerce
            skipped: Whether sync was skipped
            error: Whether sync encountered an error
            message: Sync message
            error_details: Detailed error information
            
        Returns:
            Created sync record
        """
        sync = self.model_class(
            odoo_id=odoo_id,
            odoo_name=odoo_name,
            woocommerce_id=woocommerce_id,
            instance_id=instance_id,
            created=created,
            updated=updated,
            skipped=skipped,
            error=error,
            message=message,
            error_details=error_details
        )
        self.db.add(sync)
        self.db.commit()
        self.db.refresh(sync)
        return sync
    
    def get_sync_by_odoo_id(
        self, 
        odoo_id: int, 
        instance_id: int
    ) -> Optional[T]:
        """
        Get sync record by Odoo ID.
        
        Args:
            odoo_id: Odoo entity ID
            instance_id: WooCommerce instance ID
            
        Returns:
            Sync record or None if not found
        """
        return self.db.query(self.model_class).filter(
            self.model_class.odoo_id == odoo_id,
            self.model_class.instance_id == instance_id
        ).first()
    
    def get_syncs(
        self,
        instance_id: int,
        error: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[T]:
        """
        Get sync records with optional filters.
        
        Args:
            instance_id: WooCommerce instance ID
            error: Filter by error status (True/False/None for all)
            limit: Maximum number of records to return
            offset: Number of records to skip
            
        Returns:
            List of sync records
        """
        query = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        )
        
        if error is not None:
            query = query.filter(self.model_class.error == error)
        
        return query.order_by(
            self.model_class.id.desc()
        ).offset(offset).limit(limit).all()
    
    def get_sync_stats(self, instance_id: int) -> Dict[str, int]:
        """
        Get sync statistics for an instance.
        
        Args:
            instance_id: WooCommerce instance ID
            
        Returns:
            Dictionary with counts: total, created, updated, skipped, errors
        """
        query = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        )
        
        total = query.count()
        created = query.filter(self.model_class.created == True).count()
        updated = query.filter(self.model_class.updated == True).count()
        skipped = query.filter(self.model_class.skipped == True).count()
        errors = query.filter(self.model_class.error == True).count()
        
        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }
    
    def update_sync(self, sync_id: int, **kwargs) -> Optional[T]:
        """
        Update a sync record with arbitrary fields.
        
        Args:
            sync_id: Sync record ID
            **kwargs: Fields to update
            
        Returns:
            Updated sync record or None if not found
        """
        sync = self.db.query(self.model_class).filter(
            self.model_class.id == sync_id
        ).first()
        
        if sync:
            for key, value in kwargs.items():
                if hasattr(sync, key):
                    setattr(sync, key, value)
            self.db.commit()
            self.db.refresh(sync)
        
        return sync
