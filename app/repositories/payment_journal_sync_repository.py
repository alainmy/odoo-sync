"""
Payment journal sync repository.

Handles all payment journal synchronization database operations.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from httpx import delete
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.payment_journal_sync import PaymentJournalSync
from app.repositories.base_sync_repository import BaseSyncRepository


logger = logging.getLogger(__name__)


class PaymentJournalSyncRepository(BaseSyncRepository[PaymentJournalSync]):
    """
    Repository for payment journal sync operations.

    Inherits all CRUD operations from BaseSyncRepository.
    Add payment journal-specific methods here if needed.
    """

    model_class = PaymentJournalSync

    def __init__(self, db: Session):
        self.db = db

    def create_sync_record(
        self,
        woocommerce_payment_method_id: str,
        woocommerce_payment_method_name: str,
        odoo_journal_id: int,
        odoo_journal_name: str,
        odoo_journal_type: str,
        odoo_journal_code: str,
        instance_id: int,
        created: bool = False,
        message: str = None
    ) -> PaymentJournalSync:
        """
        Create a new payment journal sync record.

        Args:
            woocommerce_payment_method_id: WooCommerce payment method ID
            woocommerce_payment_method_name: Payment method name in WooCommerce
            odoo_journal_id: Odoo journal ID
            odoo_journal_name: Journal name in Odoo
            odoo_journal_type: Journal type in Odoo (e.g., bank, cash)
            odoo_journal_code: Journal code in Odoo
            instance_id: WooCommerce instance ID
            created: Whether the record was created (for sync tracking)
            message: Optional message about the sync

        Returns:
            The created PaymentJournalSync record.
        """
        sync_record = PaymentJournalSync(
            woocommerce_payment_method_id=woocommerce_payment_method_id,
            woocommerce_payment_method_name=woocommerce_payment_method_name,
            odoo_journal_id=odoo_journal_id,
            odoo_journal_name=odoo_journal_name,
            odoo_journal_type=odoo_journal_type,
            odoo_journal_code=odoo_journal_code,
            instance_id=instance_id,
            created=created,
            message=message
        )
        self.db.add(sync_record)
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_by_woocommerce_payment_method_id_and_instance(self, woocommerce_payment_method_id: str, instance_id: int) -> Optional[PaymentJournalSync]:
        """
        Get a payment journal sync record by WooCommerce payment method ID and instance ID.

        Args:
            woocommerce_payment_method_id: WooCommerce payment method ID
            instance_id: WooCommerce instance ID

        Returns:
            The PaymentJournalSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            PaymentJournalSync.woocommerce_payment_method_id == woocommerce_payment_method_id,
            PaymentJournalSync.instance_id == instance_id
        ).first()

    def get_by_odoo_journal_id_and_instance(self, odoo_journal_id: int, instance_id: int) -> Optional[PaymentJournalSync]:
        """
        Get a payment journal sync record by Odoo journal ID and instance ID.

        Args:
            odoo_journal_id: Odoo journal ID
            instance_id: WooCommerce instance ID

        Returns:
            The PaymentJournalSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            PaymentJournalSync.odoo_journal_id == odoo_journal_id,
            PaymentJournalSync.instance_id == instance_id
        ).first()

    def update_sync_record(self, sync_record: PaymentJournalSync, **kwargs) -> PaymentJournalSync:
        """
        Update fields of a payment journal sync record.

        Args:
            sync_record: The PaymentJournalSync record to update
            kwargs: Fields to update with their new values

        Returns:
            The updated PaymentJournalSync record.
        """
        for key, value in kwargs.items():
            setattr(sync_record, key, value)
        sync_record.last_synced_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_payment_journals_with_sync_status(
        self,
        odoo_journals: List[Dict[str, Any]],
        instance_id: int,
        filter_status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Enrich Odoo journal data with sync status from PaymentJournalSync table.

        Args:
            odoo_journals: List of journal dictionaries from Odoo
            instance_id: WooCommerce instance ID
            filter_status: Optional filter: never_synced, synced, error

        Returns:
            List of journal dictionaries with sync status added
        """
        odoo_ids = [j.get("id") for j in odoo_journals if j.get("id")]
        if not odoo_ids:
            return []

        sync_records = self.db.query(PaymentJournalSync).filter(
            PaymentJournalSync.odoo_journal_id.in_(odoo_ids),
            PaymentJournalSync.instance_id == instance_id
        ).all()

        sync_map = {record.odoo_journal_id: record for record in sync_records}

        enriched_journals = []
        for journal in odoo_journals:
            journal_id = journal.get("id")
            sync_record = sync_map.get(journal_id)

            sync_status = "never_synced"
            if sync_record:
                if sync_record.error:
                    sync_status = "error"
                elif sync_record.last_synced_at:
                    sync_status = "synced"
                else:
                    sync_status = "never_synced"

            if filter_status and sync_status != filter_status:
                continue

            journal["sync_status"] = sync_status
            journal["woocommerce_payment_method_id"] = sync_record.woocommerce_payment_method_id if sync_record else None
            journal["woocommerce_payment_method_name"] = sync_record.woocommerce_payment_method_name if sync_record else None
            journal["last_synced_at"] = sync_record.last_synced_at.isoformat() if sync_record and sync_record.last_synced_at else None

            if sync_record:
                journal["sync_error"] = sync_record.error_details if sync_record.error else None

            enriched_journals.append(journal)

        return enriched_journals

    def get_all_by_instance(
        self,
        instance_id: int,
        limit: int = 100,
        offset: int = 0,
        error: Optional[bool] = None
    ) -> List[PaymentJournalSync]:
        """
        Get all payment journal sync records for a given instance.

        Args:
            instance_id: WooCommerce instance ID
            limit: Maximum number of records
            offset: Number of records to skip
            error: Filter by error status

        Returns:
            List of PaymentJournalSync records
        """
        query = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        )

        if error is not None:
            query = query.filter(self.model_class.error == error)

        return query.order_by(
            self.model_class.id.desc()
        ).offset(offset).limit(limit).all()

    def get_statistics(self, instance_id: int) -> Dict[str, Any]:
        """
        Get sync statistics for payment journal mappings.

        Args:
            instance_id: WooCommerce instance ID

        Returns:
            Dictionary with counts
        """
        base_query = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        )

        total = base_query.count()
        synced = base_query.filter(
            and_(PaymentJournalSync.last_synced_at != None, PaymentJournalSync.error == False)
        ).count()
        never_synced = total - synced
        errors = base_query.filter(PaymentJournalSync.error == True).count()

        last_sync_record = base_query.filter(
            PaymentJournalSync.last_synced_at != None
        ).order_by(PaymentJournalSync.last_synced_at.desc()).first()

        return {
            "total": total,
            "synced": synced,
            "never_synced": never_synced,
            "errors": errors,
            "last_sync": last_sync_record.last_synced_at if last_sync_record else None
        }

    def delete_all_by_instance(self, instance_id: int):
        """
        Delete all payment journal sync records for a given instance.

        Args:
            instance_id: WooCommerce instance ID
        """
        journals = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        ).all()

        for journal in journals:
            self.db.delete(journal)

        self.db.commit()
        logger.info(f"Deleted {len(journals)} payment journal sync records for instance_id={instance_id}")

    def delete_sync_record(self, sync_record: PaymentJournalSync):
        """
        Delete a payment journal sync record.

        Args:
            sync_record: The PaymentJournalSync record to delete
        """
        self.db.delete(sync_record)
        self.db.commit()

    def mark_payment_journals_for_sync(self, odoo_ids: List[int], instance_id: int) -> int:
        """
        Mark existing sync records as needing sync.

        Args:
            odoo_ids: List of Odoo journal IDs
            instance_id: WooCommerce instance ID

        Returns:
            Number of records updated
        """
        updated = self.db.query(self.model_class).filter(
            self.model_class.odoo_journal_id.in_(odoo_ids),
            self.model_class.instance_id == instance_id
        ).update({"needs_sync": True}, synchronize_session=False)

        self.db.commit()
        return updated