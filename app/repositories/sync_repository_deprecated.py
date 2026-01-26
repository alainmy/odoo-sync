"""
Repository for sync-related database operations.
"""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models.admin import (
    ProductSync,
    CategorySync,
    TagSync,
    WebhookLog,
    CeleryTaskLog,
    WooCommerceInstance
)
import logging

logger = logging.getLogger(__name__)


class SyncRepository:
    """Repository for sync operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ==================== Product Sync ====================
    
    def create_product_sync(
        self,
        odoo_id: int,
        woocommerce_id: int,
        instance_id: int,
        created: bool = False,
        updated: bool = False,
        skipped: bool = False,
        error: bool = False,
        message: str = "",
        error_details: str = ""
    ) -> ProductSync:
        """Create a product sync record."""
        sync = ProductSync(
            odoo_id=odoo_id,
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
    
    def get_product_sync_by_odoo_id(self, odoo_id: int, instance_id: int) -> Optional[ProductSync]:
        """Get product sync record by Odoo ID."""
        return self.db.query(ProductSync).filter(
            ProductSync.odoo_id == odoo_id,
            ProductSync.instance_id == instance_id
        ).first()
    
    def get_product_sync_by_wc_id(self, wc_id: int, instance_id: int) -> Optional[ProductSync]:
        """Get product sync record by WooCommerce ID."""
        return self.db.query(ProductSync).filter(
            ProductSync.woocommerce_id == wc_id,
            ProductSync.instance_id == instance_id
        ).first()
    
    def update_product_sync(
        self,
        sync_id: int,
        **kwargs
    ) -> Optional[ProductSync]:
        """Update product sync record."""
        sync = self.db.query(ProductSync).filter(ProductSync.id == sync_id).first()
        if sync:
            for key, value in kwargs.items():
                setattr(sync, key, value)
            self.db.commit()
            self.db.refresh(sync)
        return sync
    
    def get_product_sync_statistics(
        self,
        instance_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """Get product sync statistics."""
        query = self.db.query(ProductSync).filter(
            ProductSync.instance_id == instance_id
        )
        
        # Note: ProductSync doesn't have timestamp fields in current model
        # You may want to add created_at/updated_at fields
        
        total = query.count()
        created = query.filter(ProductSync.created == True).count()
        updated = query.filter(ProductSync.updated == True).count()
        skipped = query.filter(ProductSync.skipped == True).count()
        errors = query.filter(ProductSync.error == True).count()
        
        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }
    
    def get_product_syncs(
        self,
        instance_id: int,
        error: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ProductSync]:
        """Get product sync records with filters."""
        query = self.db.query(ProductSync).filter(
            ProductSync.instance_id == instance_id
        )
        
        if error is not None:
            query = query.filter(ProductSync.error == error)
        
        return query.order_by(ProductSync.id.desc()).offset(offset).limit(limit).all()
    
    # ==================== Category Sync ====================
    
    def create_category_sync(
        self,
        odoo_id: int,
        woocommerce_id: int,
        instance_id: int,
        created: bool = False,
        updated: bool = False,
        skipped: bool = False,
        error: bool = False,
        message: str = "",
        error_details: str = ""
    ) -> CategorySync:
        """Create a category sync record."""
        sync = CategorySync(
            odoo_id=odoo_id,
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
    
    def get_category_sync_by_odoo_id(self, odoo_id: int, instance_id: int) -> Optional[CategorySync]:
        """Get category sync record by Odoo ID."""
        return self.db.query(CategorySync).filter(
            CategorySync.odoo_id == odoo_id,
            CategorySync.instance_id == instance_id
        ).first()
    
    def get_category_syncs(
        self,
        instance_id: int,
        error: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[CategorySync]:
        """Get category sync records with filters."""
        query = self.db.query(CategorySync).filter(
            CategorySync.instance_id == instance_id
        )
        
        if error is not None:
            query = query.filter(CategorySync.error == error)
        
        return query.order_by(CategorySync.id.desc()).offset(offset).limit(limit).all()
    
    def get_category_sync_stats(self, instance_id: int) -> Dict[str, int]:
        """Get category sync statistics."""
        total = self.db.query(CategorySync).filter(CategorySync.instance_id == instance_id).count()
        created = self.db.query(CategorySync).filter(CategorySync.instance_id == instance_id, CategorySync.created == True).count()
        updated = self.db.query(CategorySync).filter(CategorySync.instance_id == instance_id, CategorySync.updated == True).count()
        skipped = self.db.query(CategorySync).filter(CategorySync.instance_id == instance_id, CategorySync.skipped == True).count()
        errors = self.db.query(CategorySync).filter(CategorySync.instance_id == instance_id, CategorySync.error == True).count()
        
        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }
    
    # ==================== Tag Sync ====================
    
    def create_tag_sync(
        self,
        odoo_id: int,
        woocommerce_id: int,
        instance_id: int,
        created: bool = False,
        updated: bool = False,
        skipped: bool = False,
        error: bool = False,
        message: str = "",
        error_details: str = ""
    ) -> TagSync:
        """Create a tag sync record."""
        sync = TagSync(
            odoo_id=odoo_id,
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
    
    def get_tag_sync_by_odoo_id(self, odoo_id: int, instance_id: int) -> Optional[TagSync]:
        """Get tag sync record by Odoo ID."""
        return self.db.query(TagSync).filter(
            TagSync.odoo_id == odoo_id,
            TagSync.instance_id == instance_id
        ).first()
    
    def get_tag_syncs(
        self,
        instance_id: int,
        error: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TagSync]:
        """Get tag sync records with filters."""
        query = self.db.query(TagSync).filter(
            TagSync.instance_id == instance_id
        )
        
        if error is not None:
            query = query.filter(TagSync.error == error)
        
        return query.order_by(TagSync.id.desc()).offset(offset).limit(limit).all()
    
    def get_tag_sync_stats(self, instance_id: int) -> Dict[str, int]:
        """Get tag sync statistics."""
        total = self.db.query(TagSync).filter(TagSync.instance_id == instance_id).count()
        created = self.db.query(TagSync).filter(TagSync.instance_id == instance_id, TagSync.created == True).count()
        updated = self.db.query(TagSync).filter(TagSync.instance_id == instance_id, TagSync.updated == True).count()
        skipped = self.db.query(TagSync).filter(TagSync.instance_id == instance_id, TagSync.skipped == True).count()
        errors = self.db.query(TagSync).filter(TagSync.instance_id == instance_id, TagSync.error == True).count()
        
        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }
    
    # ==================== Webhook Logs ====================
    
    def create_webhook_log(
        self,
        event_id: str,
        event_type: str,
        payload_hash: str,
        payload: Dict[str, Any],
        instance_id: int,
        status: str = "pending"
    ) -> WebhookLog:
        """Create a webhook log record."""
        log = WebhookLog(
            event_id=event_id,
            event_type=event_type,
            payload_hash=payload_hash,
            payload=payload,
            instance_id=instance_id,
            status=status
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
    
    def get_webhook_log_by_event_id(self, event_id: str) -> Optional[WebhookLog]:
        """Get webhook log by event ID."""
        return self.db.query(WebhookLog).filter(
            WebhookLog.event_id == event_id
        ).first()
    
    def get_webhook_logs(
        self,
        instance_id: int,
        status: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WebhookLog]:
        """Get webhook logs with filters."""
        query = self.db.query(WebhookLog).filter(
            WebhookLog.instance_id == instance_id
        )
        
        if status:
            query = query.filter(WebhookLog.status == status)
        if event_type:
            query = query.filter(WebhookLog.event_type == event_type)
        
        return query.order_by(WebhookLog.created_at.desc()).offset(offset).limit(limit).all()
    
    def update_webhook_log(
        self,
        event_id: str,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        processed_at: Optional[datetime] = None
    ) -> Optional[WebhookLog]:
        """Update webhook log record."""
        log = self.get_webhook_log_by_event_id(event_id)
        if log:
            if status:
                log.status = status
            if error_message:
                log.error_message = error_message
            if processed_at:
                log.processed_at = processed_at
            self.db.commit()
            self.db.refresh(log)
        return log
    
    def get_webhook_statistics(
        self,
        instance_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get webhook processing statistics."""
        query = self.db.query(WebhookLog).filter(
            WebhookLog.instance_id == instance_id
        )
        
        if start_date:
            query = query.filter(WebhookLog.created_at >= start_date)
        if end_date:
            query = query.filter(WebhookLog.created_at <= end_date)
        
        total = query.count()
        completed = query.filter(WebhookLog.status == "completed").count()
        failed = query.filter(WebhookLog.status == "failed").count()
        pending = query.filter(WebhookLog.status == "pending").count()
        
        # Get event type breakdown
        event_types = self.db.query(
            WebhookLog.event_type,
            func.count(WebhookLog.id)
        ).filter(
            and_(
                WebhookLog.instance_id == instance_id,
                WebhookLog.created_at >= start_date if start_date else True,
                WebhookLog.created_at <= end_date if end_date else True
            )
        ).group_by(WebhookLog.event_type).all()
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "event_types": {event_type: count for event_type, count in event_types}
        }
    
    # ==================== Celery Task Logs ====================
    
    def create_task_log(
        self,
        task_id: str,
        task_name: str,
        instance_id: int,
        task_args: List = None,
        task_kwargs: Dict = None,
        status: str = "pending"
    ) -> CeleryTaskLog:
        """Create a Celery task log record."""
        log = CeleryTaskLog(
            task_id=task_id,
            task_name=task_name,
            instance_id=instance_id,
            task_args=task_args or [],
            task_kwargs=task_kwargs or {},
            status=status
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
    
    def get_task_log(self, task_id: str) -> Optional[CeleryTaskLog]:
        """Get task log by task ID."""
        return self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.task_id == task_id
        ).first()
    
    def update_task_log(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[Dict] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ) -> Optional[CeleryTaskLog]:
        """Update task log record."""
        log = self.get_task_log(task_id)
        if log:
            if status:
                log.status = status
            if result:
                log.result = result
            if error_message:
                log.error_message = error_message
            if started_at:
                log.started_at = started_at
            if completed_at:
                log.completed_at = completed_at
            self.db.commit()
            self.db.refresh(log)
        return log
    
    def get_task_logs(
        self,
        instance_id: int,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        task_name: Optional[str] = None
    ) -> List[CeleryTaskLog]:
        """Get task logs with filters."""
        query = self.db.query(CeleryTaskLog).filter(
            CeleryTaskLog.instance_id == instance_id
        )
        
        if status:
            query = query.filter(CeleryTaskLog.status == status)
        if task_name:
            query = query.filter(CeleryTaskLog.task_name == task_name)
        
        return query.order_by(CeleryTaskLog.id.desc()).offset(offset).limit(limit).all()
    
    # ==================== WooCommerce Instances ====================
    
    def create_instance(
        self,
        name: str,
        url: str,
        consumer_key: str,
        consumer_secret: str,
        webhook_secret: str,
        **kwargs
    ) -> WooCommerceInstance:
        """Create a WooCommerce instance configuration."""
        instance = WooCommerceInstance(
            name=name,
            url=url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            webhook_secret=webhook_secret,
            **kwargs
        )
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance
    
    def get_instance(self, instance_id: int) -> Optional[WooCommerceInstance]:
        """Get WooCommerce instance by ID."""
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()
    
    def get_instance_by_name(self, name: str) -> Optional[WooCommerceInstance]:
        """Get WooCommerce instance by name."""
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.name == name
        ).first()
    
    def get_active_instances(self) -> List[WooCommerceInstance]:
        """Get all active WooCommerce instances."""
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.is_active == True
        ).all()
    
    def get_all_instances(self) -> List[WooCommerceInstance]:
        """Get all WooCommerce instances."""
        return self.db.query(WooCommerceInstance).all()
    
    # ==================== Sync Management ====================
    
    def get_products_with_sync_status(
        self,
        odoo_products: List[Dict],
        instance_id: int,
        filter_status: Optional[str] = None
    ) -> Tuple[List[Dict], int]:
        """
        Enrich Odoo products with sync status from ProductSync table.
        
        Args:
            odoo_products: List of products from Odoo search_read
            instance_id: WooCommerce instance ID
            filter_status: Filter by status (never_synced, synced, modified, error)
            
        Returns:
            Tuple of (enriched_products, total_count)
        """
        if not odoo_products:
            return [], 0
        
        # Extract odoo_ids
        odoo_ids = [p["id"] for p in odoo_products]
        
        # Bulk fetch ProductSync records
        sync_records = self.db.query(ProductSync).filter(
            ProductSync.odoo_id.in_(odoo_ids),
            ProductSync.instance_id == instance_id
        ).all()
        
        # Create lookup map
        sync_map = {s.odoo_id: s for s in sync_records}
        
        enriched = []
        for product in odoo_products:
            sync_record = sync_map.get(product["id"])
            sync_status = self._calculate_sync_status(product, sync_record)
            
            # Apply filter
            if filter_status and sync_status != filter_status:
                continue
            
            enriched.append({
                "odoo_id": product["id"],
                "name": product.get("name", ""),
                "sku": product.get("default_code") if product.get("default_code") else None,
                "price": product.get("list_price"),
                "odoo_write_date": product.get("write_date"),
                "sync_status": sync_status,
                "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
                "last_synced_at": sync_record.last_synced_at if sync_record else None,
                "needs_sync": sync_record.needs_sync if sync_record else False,
                "published": sync_record.published if sync_record else False,
                "has_error": sync_record.error if sync_record else False,
                "error_message": sync_record.message if sync_record and sync_record.error else None
            })
        
        return enriched, len(enriched)
    
    def _calculate_sync_status(
        self, 
        odoo_product: dict, 
        sync: Optional[ProductSync]
    ) -> str:
        """
        Calculate sync status based on timestamps and flags.
        
        Returns: "never_synced", "synced", "modified", "error"
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
            odoo_write_date_str = odoo_product.get("write_date")
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
            logger.warning(f"Error parsing dates for product {odoo_product.get('id')}: {e}")
            return "synced"
        
        return "synced"
    
    def mark_products_for_sync(self, odoo_ids: List[int], instance_id: int) -> int:
        """
        Bulk update needs_sync flag to True for given Odoo IDs.
        
        Returns: Number of records updated
        """
        count = self.db.query(ProductSync).filter(
            ProductSync.odoo_id.in_(odoo_ids),
            ProductSync.instance_id == instance_id
        ).update({"needs_sync": True}, synchronize_session=False)
        self.db.commit()
        return count
    
    def get_products_needing_sync(
        self,
        instance_id: int,
        limit: int = 100
    ) -> List[ProductSync]:
        """Get products marked as needing sync."""
        return self.db.query(ProductSync).filter(
            ProductSync.needs_sync == True,
            ProductSync.instance_id == instance_id
        ).limit(limit).all()
    
    def update_product_sync_timestamps(
        self,
        odoo_id: int,
        instance_id: int,
        wc_id: Optional[int] = None,
        odoo_write_date: Optional[datetime] = None,
        last_synced_at: Optional[datetime] = None,
        published: Optional[bool] = None,
        needs_sync: bool = False,
        created: Optional[bool] = None,
        updated: Optional[bool] = None,
        message: Optional[str] = None
    ) -> Optional[ProductSync]:
        """Update sync record with timestamps after successful sync. Creates record if doesn't exist."""
        sync = self.get_product_sync_by_odoo_id(odoo_id, instance_id)
        
        if sync:
            # Update existing record
            if wc_id is not None:
                sync.woocommerce_id = wc_id
            if odoo_write_date is not None:
                sync.odoo_write_date = odoo_write_date
            if last_synced_at is not None:
                sync.last_synced_at = last_synced_at
                sync.sync_date = last_synced_at
            if published is not None:
                sync.published = published
            if created is not None:
                sync.created = created
            if updated is not None:
                sync.updated = updated
            if message is not None:
                sync.message = message
            sync.needs_sync = needs_sync
            sync.error = False  # Clear error on successful sync
            
            self.db.commit()
            self.db.refresh(sync)
        else:
            # Create new record if doesn't exist
            sync = ProductSync(
                odoo_id=odoo_id,
                woocommerce_id=wc_id,
                instance_id=instance_id,
                odoo_write_date=odoo_write_date,
                last_synced_at=last_synced_at,
                sync_date=last_synced_at,
                published=published if published is not None else False,
                needs_sync=needs_sync,
                created=created if created is not None else False,
                updated=updated if updated is not None else False,
                message=message,
                error=False
            )
            self.db.add(sync)
            self.db.commit()
            self.db.refresh(sync)
        
        return sync


def get_sync_repository(db: Session) -> SyncRepository:
    """Dependency injection for SyncRepository."""
    return SyncRepository(db)
