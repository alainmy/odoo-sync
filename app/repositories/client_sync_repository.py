"""
Category sync repository.

Handles all category synchronization database operations.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.user_model import ClientSync
from app.repositories.base_sync_repository import BaseSyncRepository


class ClientSyncRepository(BaseSyncRepository[ClientSync]):
    """
    Repository for client sync operations.

    Inherits all CRUD operations from BaseSyncRepository.
    Add client-specific methods here if needed.
    """

    def __init__(self, db: Session):
        self.db = db
    model_class = ClientSync

    def create_sync_record(self, odoo_id: int,
                           woo_id: int,
                           email: str,
                           name: str,
                           contact_type: str = None,
                           last_name: str = None,
                           parent_id: int = None,
                           sync_status: str = "synced",
                           last_synced_at: datetime = None) -> ClientSync:
        """
        Create a new client sync record.

        Args:
            odoo_id: Odoo client ID
            woo_id: WooCommerce client ID
            email: Client email address
            name: Client name
            contact_type: Type of contact (contact, billing, shipping, etc.)
            last_name: Client last name
            parent_id: Parent client ID for hierarchical relationships
            sync_status: Sync status (synced, pending, failed, etc.)
            last_synced_at: Timestamp of last sync

        Returns:
            The created ClientSync record.
        """
        sync_record = ClientSync(
            odoo_id=odoo_id,
            woo_id=woo_id,
            email=email,
            name=name,
            contact_type=contact_type,
            last_name=last_name,
            parent_id=parent_id,
            sync_status=sync_status,
            last_synced_at=last_synced_at
        )
        self.db.add(sync_record)
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_by_odoo_id(self, odoo_id: int) -> ClientSync:
        """
        Get a client sync record by Odoo ID.

        Args:
            odoo_id: Odoo client ID
        Returns:
            The ClientSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            ClientSync.odoo_id == odoo_id
        ).first()

    def get_by_woo_id(self, woo_id: int) -> ClientSync:
        """
        Get a client sync record by WooCommerce ID.

        Args:
            woo_id: WooCommerce client ID
        Returns:
            The ClientSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            ClientSync.woo_id == woo_id
        ).first()

    def get_by_email(self, email: str) -> ClientSync:
        """
        Get a client sync record by email.

        Args:
            email: Client email address
        Returns:
            The ClientSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            ClientSync.email == email
        ).first()

    def get_by_contact_type(self, parent_id: int, contact_type: str) -> ClientSync:
        """
        Get a client sync record by parent ID and contact type.

        Args:
            parent_id: Parent client ID
            contact_type: Type of contact (billing, shipping, etc.)
        Returns:
            The ClientSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            ClientSync.parent_id == parent_id,
            ClientSync.contact_type == contact_type
        ).first()

    def update_sync_record(self, sync_record: ClientSync, **kwargs) -> ClientSync:
        """
        Update fields of a client sync record.

        Args:
            sync_record: The ClientSync record to update
            kwargs: Fields to update with their new values

        Returns:
            The updated ClientSync record.
        """
        for key, value in kwargs.items():
            if hasattr(sync_record, key):
                setattr(sync_record, key, value)
        sync_record.last_synced_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record
