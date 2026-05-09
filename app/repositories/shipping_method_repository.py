"""
Shipping method sync repository.

Handles all shipping method synchronization database operations.
"""
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.shipping_method_sync import ShippingMethodSync
from app.repositories.base_sync_repository import BaseSyncRepository

logger = logging.getLogger(__name__)


class ShippingMethodRepository(BaseSyncRepository[ShippingMethodSync]):
    """Repository for shipping method sync operations."""

    model_class = ShippingMethodSync

    def get_shipping_method_by_wc_id(
        self,
        wc_id: int,
        instance_id: int
    ) -> Optional[ShippingMethodSync]:
        """
        Get shipping method sync record by WooCommerce ID.

        Args:
            wc_id: WooCommerce shipping method ID
            instance_id: WooCommerce instance ID

        Returns:
            ShippingMethodSync record or None
        """
        return self.db.query(ShippingMethodSync).filter(
            ShippingMethodSync.woocommerce_id == wc_id,
            ShippingMethodSync.instance_id == instance_id
        ).first()

    def get_shipping_method_statistics(
        self,
        instance_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Get shipping method sync statistics.

        Args:
            instance_id: WooCommerce instance ID
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary with sync statistics
        """
        query = self.db.query(ShippingMethodSync).filter(
            ShippingMethodSync.instance_id == instance_id
        )

        # Note: ShippingMethodSync doesn't have created_at/updated_at fields in current model
        # You may want to add these fields for time-based filtering

        total = query.count()
        created = query.filter(ShippingMethodSync.created == True).count()
        updated = query.filter(ShippingMethodSync.updated == True).count()
        skipped = query.filter(ShippingMethodSync.skipped == True).count()
        errors = query.filter(ShippingMethodSync.error == True).count()

        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }

    def get_shipping_methods_with_sync_status(
        self,
        odoo_carriers: List[Dict],
        instance_id: int,
        filter_status: Optional[str] = None
    ) -> Tuple[List[Dict], int]:
        """
        Enrich Odoo carriers with sync status from ShippingMethodSync table.

        Args:
            odoo_carriers: List of carriers from Odoo search_read
            instance_id: WooCommerce instance ID
            filter_status: Filter by status (never_synced, synced, modified, error)

        Returns:
            Tuple of (enriched_carriers, total_count)
        """
        if not odoo_carriers:
            return [], 0

        # Extract odoo_ids
        odoo_ids = [c["id"] for c in odoo_carriers]

        # Bulk fetch ShippingMethodSync records
        sync_records = self.db.query(ShippingMethodSync).filter(
            ShippingMethodSync.odoo_id.in_(odoo_ids),
            ShippingMethodSync.instance_id == instance_id
        ).all()

        # Create lookup map
        sync_map = {s.odoo_id: s for s in sync_records}

        enriched = []
        for carrier in odoo_carriers:
            sync_record = sync_map.get(carrier["id"])
            sync_status = self._calculate_sync_status(carrier, sync_record)

            # Apply filter
            if filter_status and sync_status != filter_status:
                continue

            enriched.append({
                "odoo_id": carrier["id"],
                "name": carrier.get("name", ""),
                "fixed_price": carrier.get("fixed_price"),
                "amount": carrier.get("amount"),
                "free_over": carrier.get("free_over"),
                "product_id": carrier.get("product_id"),
                "country_ids": carrier.get("country_ids"),
                "state_ids": carrier.get("state_ids"),
                "sync_status": sync_status,
                "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
                "last_synced_at": sync_record.last_synced_at if sync_record else None,
                "needs_sync": sync_record.needs_sync if sync_record else False,
                "has_error": sync_record.error if sync_record else False,
                "error_message": sync_record.message if sync_record and sync_record.error else None
            })

        return enriched, len(enriched)

    def _calculate_sync_status(
        self,
        odoo_carrier: dict,
        sync: Optional[ShippingMethodSync]
    ) -> str:
        """
        Calculate sync status based on timestamps and flags.

        Args:
            odoo_carrier: Carrier data from Odoo
            sync: ShippingMethodSync record (may be None)

        Returns:
            Sync status: "never_synced", "synced", "modified", "error"
        """
        # No sync record = never synced
        if not sync:
            return "never_synced"

        # Error state takes precedence
        if sync.error:
            return "error"

        # Never synced if no last_synced_at
        if not sync.last_synced_at:
            return "never_synced"

        # Compare Odoo write_date with last_synced_at
        try:
            odoo_write_date_str = odoo_carrier.get("write_date")
            if not odoo_write_date_str:
                return "synced"

            # Parse Odoo datetime string (format: "2024-01-15 10:30:45")
            odoo_write_dt = datetime.fromisoformat(
                odoo_write_date_str.replace(" ", "T")
            )

            # Make timezone-aware if needed
            if odoo_write_dt.tzinfo is None:
                from datetime import timezone
                odoo_write_dt = odoo_write_dt.replace(tzinfo=timezone.utc)

            last_synced = sync.last_synced_at
            if last_synced.tzinfo is None:
                from datetime import timezone
                last_synced = last_synced.replace(tzinfo=timezone.utc)

            # If Odoo modified after last sync = modified
            # Use 10-second tolerance like ks_woocommerce
            tolerance = timedelta(seconds=10)
            if odoo_write_dt > (last_synced + tolerance):
                return "modified"

        except (ValueError, AttributeError) as e:
            logger.warning(
                f"Error parsing dates for carrier {odoo_carrier.get('id')}: {e}"
            )
            return "synced"

        return "synced"

    def mark_carriers_for_sync(
        self,
        odoo_ids: List[int],
        instance_id: int
    ) -> int:
        """
        Bulk update needs_sync flag to True for given Odoo IDs.

        Args:
            odoo_ids: List of Odoo carrier IDs
            instance_id: WooCommerce instance ID

        Returns:
            Number of records updated
        """
        count = self.db.query(ShippingMethodSync).filter(
            ShippingMethodSync.odoo_id.in_(odoo_ids),
            ShippingMethodSync.instance_id == instance_id
        ).update({"needs_sync": True}, synchronize_session=False)
        self.db.commit()
        return count

    def get_carriers_needing_sync(
        self,
        instance_id: int,
        limit: int = 100
    ) -> List[ShippingMethodSync]:
        """
        Get carriers marked as needing sync.

        Args:
            instance_id: WooCommerce instance ID
            limit: Maximum number of carriers to return

        Returns:
            List of ShippingMethodSync records needing sync
        """
        return self.db.query(ShippingMethodSync).filter(
            ShippingMethodSync.needs_sync == True,
            ShippingMethodSync.instance_id == instance_id
        ).limit(limit).all()

    def update_shipping_method_sync_timestamps(
        self,
        odoo_id: int,
        instance_id: int,
        odoo_name: Optional[str] = None,
        wc_id: Optional[int] = None,
        odoo_write_date: Optional[datetime] = None,
        last_synced_at: Optional[datetime] = None,
        needs_sync: bool = False,
        created: Optional[bool] = None,
        updated: Optional[bool] = None,
        message: Optional[str] = None
    ) -> Optional[ShippingMethodSync]:
        """
        Update sync record with timestamps after successful sync.
        Creates record if it doesn't exist.

        Args:
            odoo_id: Odoo carrier ID
            instance_id: WooCommerce instance ID
            wc_id: WooCommerce shipping method ID
            odoo_write_date: Carrier write date from Odoo
            last_synced_at: Timestamp of successful sync
            needs_sync: Whether carrier needs sync
            created: Whether carrier was created
            updated: Whether carrier was updated
            message: Sync message

        Returns:
            Updated or created ShippingMethodSync record
        """
        sync = self.get_sync_by_odoo_id(odoo_id, instance_id)

        if sync:
            # Update existing record
            if wc_id is not None:
                sync.woocommerce_id = wc_id
            if odoo_write_date is not None:
                sync.odoo_write_date = odoo_write_date
            if odoo_name is not None:
                sync.odoo_name = odoo_name
            if last_synced_at is not None:
                sync.last_synced_at = last_synced_at
                sync.sync_date = last_synced_at
            if message is not None:
                sync.message = message
            sync.needs_sync = needs_sync
            sync.error = False  # Clear error on successful sync

            self.db.commit()
            self.db.refresh(sync)
        else:
            # Create new record if doesn't exist
            sync = ShippingMethodSync(
                odoo_id=odoo_id,
                woocommerce_id=wc_id,
                instance_id=instance_id,
                odoo_write_date=odoo_write_date,
                last_synced_at=last_synced_at,
                sync_date=last_synced_at,
                needs_sync=needs_sync,
                created=created if created is not None else False,
                updated=updated if updated is not None else False,
                message=message,
                odoo_name=odoo_name if odoo_name is not None else None,
                error=False
            )
            self.db.add(sync)
            self.db.commit()
            self.db.refresh(sync)

        return sync