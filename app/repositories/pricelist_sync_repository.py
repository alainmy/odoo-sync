"""Repository for pricelist sync operations."""

import logging
from typing import Optional, List
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.pricelist_models import PricelistSync
from app.schemas.pricelist_schemas import PricelistSyncCreate, PricelistSyncUpdate

logger = logging.getLogger(__name__)


class PricelistSyncRepository:
    """Repository for managing pricelist sync records."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, sync_id: int) -> Optional[PricelistSync]:
        """Get pricelist sync by ID."""
        return self.db.query(PricelistSync).filter(PricelistSync.id == sync_id).first()

    def get_by_odoo_pricelist(
        self,
        odoo_pricelist_id: int,
        instance_id: int
    ) -> Optional[PricelistSync]:
        """Get pricelist sync by Odoo pricelist ID and instance ID."""
        return self.db.query(PricelistSync).filter(
            PricelistSync.odoo_pricelist_id == odoo_pricelist_id,
            PricelistSync.instance_id == instance_id
        ).first()

    def get_all_by_instance(self, instance_id: int) -> List[PricelistSync]:
        """Get all pricelist syncs for an instance."""
        return self.db.query(PricelistSync).filter(
            PricelistSync.instance_id == instance_id
        ).all()

    def get_active_by_instance(self, instance_id: int) -> List[PricelistSync]:
        """Get all active pricelist syncs for an instance."""
        return self.db.query(PricelistSync).filter(
            PricelistSync.instance_id == instance_id,
            PricelistSync.active == True
        ).all()

    def create(self, pricelist_sync: PricelistSyncCreate) -> Optional[PricelistSync]:
        """
        Create a new pricelist sync record.

        Args:
            pricelist_sync: Pricelist sync data

        Returns:
            Created PricelistSync or None if error
        """
        try:
            db_sync = PricelistSync(
                odoo_pricelist_id=pricelist_sync.odoo_pricelist_id,
                odoo_pricelist_name=pricelist_sync.odoo_pricelist_name,
                instance_id=pricelist_sync.instance_id,
                active=pricelist_sync.active,
                price_type=pricelist_sync.price_type,
                meta_key=pricelist_sync.meta_key,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            self.db.add(db_sync)
            self.db.commit()
            self.db.refresh(db_sync)

            logger.info(
                f"Created pricelist sync: Odoo {pricelist_sync.odoo_pricelist_id} "
                f"-> Instance {pricelist_sync.instance_id}"
            )
            return db_sync

        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"IntegrityError creating pricelist sync: {e}")
            return None
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating pricelist sync: {e}")
            return None

    def activate_price_list(self,
                            price_list_id: int):

        price_list = self.db.query(PricelistSync).filter(
            PricelistSync.id == price_list_id).first()

        if not price_list:
            raise HTTPException(
                status_code=404, detail="Price List not found."
            )
        all_price_list = self.db.query(PricelistSync.id).filter(
            PricelistSync.id != price_list_id).all()
        for item in all_price_list:
            item.active = False
            self.db.commit()
            self.db.refresh(item)
        price_list.active = True
        self.db.commit()
        self.db.refresh(price_list)

    def inactivate_price_list(self,
                              price_list_id: int):

        price_list = self.db.query(PricelistSync).filter(PricelistSync.id == price_list_id).first()

        if not price_list:
            raise HTTPException(
                status_code=404, detail="Price List not found."
            )
        all_price_list = self.db.query(PricelistSync).filter(PricelistSync.id != price_list_id).all()
        for item in all_price_list:
            item.active = False
            self.db.commit()
            self.db.refresh(item)

    def update(
        self,
        sync_id: int,
        update_data: PricelistSyncUpdate
    ) -> Optional[PricelistSync]:
        """
        Update a pricelist sync record.

        Args:
            sync_id: Pricelist sync ID
            update_data: Data to update

        Returns:
            Updated PricelistSync or None if not found
        """
        try:
            db_sync = self.get_by_id(sync_id)
            if not db_sync:
                logger.warning(f"Pricelist sync {sync_id} not found")
                return None

            update_dict = update_data.dict(exclude_unset=True)
            for key, value in update_dict.items():
                setattr(db_sync, key, value)
                if key == 'active' and value == True:
                    self.inactivate_price_list(sync_id)

            db_sync.updated_at = datetime.utcnow()

            self.db.commit()
            self.db.refresh(db_sync)

            logger.info(f"Updated pricelist sync {sync_id}")
            return db_sync

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating pricelist sync {sync_id}: {e}")
            return None

    def update_sync_status(
        self,
        sync_id: int,
        message: str,
        last_synced_at: Optional[datetime] = None
    ) -> Optional[PricelistSync]:
        """
        Update sync status and message.

        Args:
            sync_id: Pricelist sync ID
            message: Sync message
            last_synced_at: Last sync timestamp

        Returns:
            Updated PricelistSync or None if not found
        """
        try:
            db_sync = self.get_by_id(sync_id)
            if not db_sync:
                return None

            db_sync.message = message
            db_sync.last_synced_at = last_synced_at or datetime.utcnow()
            db_sync.updated_at = datetime.utcnow()

            self.db.commit()
            self.db.refresh(db_sync)

            return db_sync

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating sync status for {sync_id}: {e}")
            return None

    def delete(self, sync_id: int) -> bool:
        """
        Delete a pricelist sync record.

        Args:
            sync_id: Pricelist sync ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            db_sync = self.get_by_id(sync_id)
            if not db_sync:
                logger.warning(
                    f"Pricelist sync {sync_id} not found for deletion")
                return False

            self.db.delete(db_sync)
            self.db.commit()

            logger.info(f"Deleted pricelist sync {sync_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting pricelist sync {sync_id}: {e}")
            return False
