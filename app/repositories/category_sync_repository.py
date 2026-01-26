"""
Category sync repository.

Handles all category synchronization database operations.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.admin import CategorySync
from app.repositories.base_sync_repository import BaseSyncRepository


class CategorySyncRepository(BaseSyncRepository[CategorySync]):
    """
    Repository for category sync operations.

    Inherits all CRUD operations from BaseSyncRepository.
    Add category-specific methods here if needed.
    """

    def __init__(self, db: Session):
        self.db = db
    model_class = CategorySync

    def create_sync_record(self, odoo_id: int,
                           woocommerce_id: int,
                           odoo_name: str,
                           instance_id: int,
                           created: bool = False,
                           last_synced_at: datetime = None,
                           message: str = None) -> CategorySync:
        """
        Create a new category sync record.

        Args:
            odoo_id: Odoo category ID
            woocommerce_id: WooCommerce category ID
            instance_id: WooCommerce instance ID
            created: Whether the record was created
            last_synced_at: Timestamp of last sync
            message: Optional message about the sync

        Returns:
            The created CategorySync record.
        """
        sync_record = CategorySync(
            odoo_id=odoo_id,
            woocommerce_id=woocommerce_id,
            odoo_name=odoo_name,
            instance_id=instance_id,
            created=created,
            last_synced_at=last_synced_at,
            message=message
        )
        self.db.add(sync_record)
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_by_odoo_id_and_instance(self, odoo_id: int, instance_id: int) -> CategorySync:
        """
        Get a category sync record by Odoo ID and instance ID.

        Args:
            odoo_id: Odoo category ID
            instance_id: WooCommerce instance ID
        Returns:
            The CategorySync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            CategorySync.odoo_id == odoo_id,
            CategorySync.instance_id == instance_id
        ).first()

    def update_sync_record(self, sync_record: CategorySync, **kwargs) -> CategorySync:
        """
        Update fields of a category sync record.

        Args:
            sync_record: The CategorySync record to update
            kwargs: Fields to update with their new values

        Returns:
            The updated CategorySync record.
        """
        for key, value in kwargs.items():
            setattr(sync_record, key, value)
        sync_record.last_synced_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record
