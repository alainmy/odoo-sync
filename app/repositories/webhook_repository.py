"""
Webhook repository.

Handles webhook log database operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models.admin import WebhookLog


class WebhookRepository:
    """Repository for webhook log operations."""
    
    def __init__(self, db: Session):
        """
        Initialize repository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def create_webhook_log(
        self,
        event_id: str,
        event_type: str,
        payload_hash: str,
        payload: Dict[str, Any],
        instance_id: int,
        status: str = "pending"
    ) -> WebhookLog:
        """
        Create a webhook log record.
        
        Args:
            event_id: Unique webhook event ID
            event_type: Type of webhook event (e.g., "product.created")
            payload_hash: Hash of webhook payload
            payload: Full webhook payload
            instance_id: WooCommerce instance ID
            status: Initial status (default: "pending")
            
        Returns:
            Created WebhookLog record
        """
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
        """
        Get webhook log by event ID.
        
        Args:
            event_id: Webhook event ID
            
        Returns:
            WebhookLog record or None
        """
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
        """
        Get webhook logs with filters.
        
        Args:
            instance_id: WooCommerce instance ID
            status: Filter by status (e.g., "pending", "completed", "failed")
            event_type: Filter by event type
            limit: Maximum number of records
            offset: Number of records to skip
            
        Returns:
            List of WebhookLog records
        """
        query = self.db.query(WebhookLog).filter(
            WebhookLog.instance_id == instance_id
        )
        
        if status:
            query = query.filter(WebhookLog.status == status)
        if event_type:
            query = query.filter(WebhookLog.event_type == event_type)
        
        return query.order_by(
            WebhookLog.created_at.desc()
        ).offset(offset).limit(limit).all()
    
    def update_webhook_log(
        self,
        event_id: str,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        processed_at: Optional[datetime] = None
    ) -> Optional[WebhookLog]:
        """
        Update webhook log record.
        
        Args:
            event_id: Webhook event ID
            status: New status
            error_message: Error message if processing failed
            processed_at: Timestamp when webhook was processed
            
        Returns:
            Updated WebhookLog record or None
        """
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
        """
        Get webhook processing statistics.
        
        Args:
            instance_id: WooCommerce instance ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            Dictionary with statistics: total, completed, failed, pending, event_types
        """
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
        event_types_query = self.db.query(
            WebhookLog.event_type,
            func.count(WebhookLog.id)
        ).filter(
            WebhookLog.instance_id == instance_id
        )
        
        if start_date:
            event_types_query = event_types_query.filter(
                WebhookLog.created_at >= start_date
            )
        if end_date:
            event_types_query = event_types_query.filter(
                WebhookLog.created_at <= end_date
            )
        
        event_types = event_types_query.group_by(WebhookLog.event_type).all()
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "event_types": {event_type: count for event_type, count in event_types}
        }
