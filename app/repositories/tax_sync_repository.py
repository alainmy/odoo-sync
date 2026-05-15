"""
Tax sync repository.

Handles all tax synchronization database operations.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.tax_sync import TaxSync
from app.repositories.base_sync_repository import BaseSyncRepository


logger = logging.getLogger(__name__)


class TaxSyncRepository(BaseSyncRepository[TaxSync]):
    """
    Repository for tax sync operations.

    Inherits all CRUD operations from BaseSyncRepository.
    Add tax-specific methods here if needed.
    """

    model_class = TaxSync

    def __init__(self, db: Session):
        self.db = db

    def create_sync_record(
        self,
        odoo_id: int,
        woocommerce_id: int,
        odoo_name: str,
        instance_id: int,
        odoo_description: str = None,
        rate: float = None,
        amount: float = None,
        price_include: bool = False,
        tax_scope: str = None,
        type_tax_use: str = None,
        active: bool = True,
        created: bool = False,
        last_synced_at: datetime = None,
        message: str = None
    ) -> TaxSync:
        """
        Create a new tax sync record.

        Args:
            odoo_id: Odoo tax ID
            woocommerce_id: WooCommerce tax ID
            odoo_name: Tax name in Odoo
            instance_id: WooCommerce instance ID
            odoo_description: Tax description from Odoo
            rate: Tax rate (percentage)
            amount: Tax amount
            price_include: Whether price includes tax
            tax_scope: Tax scope (sales/purchase)
            type_tax_use: Odoo tax type
            active: Whether tax is active
            created: Whether the record was created
            last_synced_at: Timestamp of last sync
            message: Optional message about the sync

        Returns:
            The created TaxSync record.
        """
        sync_record = TaxSync(
            odoo_id=odoo_id,
            woocommerce_id=woocommerce_id,
            odoo_name=odoo_name,
            odoo_description=odoo_description,
            instance_id=instance_id,
            rate=rate,
            amount=amount,
            price_include=price_include,
            tax_scope=tax_scope,
            type_tax_use=type_tax_use,
            active=active,
            created=created,
            last_synced_at=last_synced_at,
            message=message
        )
        self.db.add(sync_record)
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_by_odoo_id_and_instance(self, odoo_id: int, instance_id: int) -> Optional[TaxSync]:
        """
        Get a tax sync record by Odoo ID and instance ID.

        Args:
            odoo_id: Odoo tax ID
            instance_id: WooCommerce instance ID
        Returns:
            The TaxSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            TaxSync.odoo_id == odoo_id,
            TaxSync.instance_id == instance_id
        ).first()

    def get_by_woocommerce_id_and_instance(self, woocommerce_id: int, instance_id: int) -> Optional[TaxSync]:
        """
        Get a tax sync record by WooCommerce ID and instance ID.

        Args:
            woocommerce_id: WooCommerce tax ID
            instance_id: WooCommerce instance ID
        Returns:
            The TaxSync record if found, else None.
        """
        return self.db.query(self.model_class).filter(
            TaxSync.woocommerce_id == woocommerce_id,
            TaxSync.instance_id == instance_id
        ).first()

    def update_sync_record(self, sync_record: TaxSync, **kwargs) -> TaxSync:
        """
        Update fields of a tax sync record.

        Args:
            sync_record: The TaxSync record to update
            kwargs: Fields to update with their new values

        Returns:
            The updated TaxSync record.
        """
        for key, value in kwargs.items():
            setattr(sync_record, key, value)
        sync_record.last_synced_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(sync_record)
        return sync_record

    def get_taxes_with_sync_status(
        self,
        odoo_taxes: List[Dict[str, Any]],
        instance_id: int,
        filter_status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Enrich Odoo tax data with sync status from TaxSync table.

        Args:
            odoo_taxes: List of tax dictionaries from Odoo
            instance_id: WooCommerce instance ID
            filter_status: Optional filter: never_synced, synced, modified, error

        Returns:
            List of tax dictionaries with sync status added
        """
        odoo_ids = [t.get("id") for t in odoo_taxes if t.get("id")]
        if not odoo_ids:
            return []

        sync_records = self.db.query(TaxSync).filter(
            TaxSync.odoo_id.in_(odoo_ids),
            TaxSync.instance_id == instance_id
        ).all()

        sync_map = {record.odoo_id: record for record in sync_records}

        enriched_taxes = []
        for tax in odoo_taxes:
            tax_id = tax.get("id")
            sync_record = sync_map.get(tax_id)

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

            tax["sync_status"] = sync_status
            tax["woocommerce_id"] = sync_record.woocommerce_id if sync_record else None
            tax["last_synced_at"] = sync_record.last_synced_at.isoformat() if sync_record and sync_record.last_synced_at else None

            if sync_record:
                tax["sync_error"] = sync_record.error_details if sync_record.error else None

            enriched_taxes.append(tax)

        return enriched_taxes

    def get_all_by_instance(
        self,
        instance_id: int,
        limit: int = 100,
        offset: int = 0,
        error: Optional[bool] = None
    ) -> List[TaxSync]:
        """
        Get all tax sync records for a given instance.

        Args:
            instance_id: WooCommerce instance ID
            limit: Maximum number of records
            offset: Number of records to skip
            error: Filter by error status

        Returns:
            List of TaxSync records
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
        Get sync statistics for taxes.

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
            and_(TaxSync.last_synced_at != None, TaxSync.error == False)
        ).count()
        never_synced = total - synced
        errors = base_query.filter(TaxSync.error == True).count()

        last_sync_record = base_query.filter(
            TaxSync.last_synced_at != None
        ).order_by(TaxSync.last_synced_at.desc()).first()

        return {
            "total": total,
            "synced": synced,
            "never_synced": never_synced,
            "errors": errors,
            "last_sync": last_sync_record.last_synced_at if last_sync_record else None
        }

    def delete_all_by_instance(self, instance_id: int):
        """
        Delete all tax sync records for a given instance.

        Args:
            instance_id: WooCommerce instance ID
        """
        taxes = self.db.query(self.model_class).filter(
            self.model_class.instance_id == instance_id
        ).all()

        for tax in taxes:
            self.db.delete(tax)

        self.db.commit()
        logger.info(f"Deleted {len(taxes)} tax sync records for instance_id={instance_id}")

    def mark_taxes_for_sync(self, odoo_ids: List[int], instance_id: int) -> int:
        """
        Mark existing sync records as needing sync.

        Args:
            odoo_ids: List of Odoo tax IDs
            instance_id: WooCommerce instance ID

        Returns:
            Number of records updated
        """
        updated = self.db.query(self.model_class).filter(
            self.model_class.odoo_id.in_(odoo_ids),
            self.model_class.instance_id == instance_id
        ).update({"needs_sync": True}, synchronize_session=False)

        self.db.commit()
        return updated