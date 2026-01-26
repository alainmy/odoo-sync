"""
Celery tasks for processing WooCommerce webhooks with idempotency.
"""
import logging
import hashlib
import hmac
import json
from datetime import datetime
from typing import Dict, Any
from celery import Task
from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.admin import WebhookLog
from app.tasks.sync_tasks import sync_product_to_odoo, sync_order_to_odoo

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


def validate_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Validate WooCommerce webhook signature using HMAC-SHA256.
    
    Args:
        payload: Raw webhook payload bytes
        signature: Signature from X-WC-Webhook-Signature header
        secret: Webhook secret key
        
    Returns:
        True if signature is valid
    """
    computed_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).digest()
    
    expected_signature = hashlib.sha256(computed_signature).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash of webhook payload for deduplication.
    
    Args:
        payload: Webhook payload dictionary
        
    Returns:
        Hexadecimal hash string
    """
    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.webhook_tasks.process_webhook",
    max_retries=3,
    default_retry_delay=120
)
def process_webhook(
    self,
    event_type: str,
    payload: Dict[str, Any],
    instance_id: int,
    event_id: str = None
) -> Dict[str, Any]:
    """
    Process WooCommerce webhook with idempotency.
    
    Args:
        event_type: Type of event (e.g., "product.created", "order.created")
        payload: Webhook payload data
        instance_id: WooCommerce instance ID
        event_id: Unique event identifier
        
    Returns:
        Dict with processing result
    """
    try:
        logger.info(f"Processing webhook: {event_type} (ID: {event_id}) for instance {instance_id}")
        
        # Get instance configuration
        from app.models.admin import WooCommerceInstance
        instance = self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()
        
        if not instance:
            logger.error(f"Instance {instance_id} not found")
            return {
                "success": False,
                "error": f"Instance {instance_id} not found"
            }
        
        # Compute payload hash for deduplication
        payload_hash = compute_payload_hash(payload)
        
        # Generate event_id if not provided
        if not event_id:
            event_id = f"{event_type}_{payload.get('id', 'unknown')}_{payload_hash[:8]}"
        
        # Check if webhook already processed (idempotency)
        existing_log = self.db.query(WebhookLog).filter(
            WebhookLog.event_id == event_id
        ).first()
        
        if existing_log:
            if existing_log.status == "completed":
                logger.info(f"Webhook {event_id} already processed, skipping")
                return {
                    "success": True,
                    "action": "skipped",
                    "message": "Webhook already processed",
                    "event_id": event_id
                }
            elif existing_log.status == "processing":
                logger.warning(f"Webhook {event_id} is being processed by another worker")
                return {
                    "success": False,
                    "action": "duplicate",
                    "message": "Webhook is being processed",
                    "event_id": event_id
                }
        
        # Create or update webhook log
        if existing_log:
            webhook_log = existing_log
            webhook_log.retry_count += 1
            webhook_log.status = "processing"
        else:
            webhook_log = WebhookLog(
                event_id=event_id,
                event_type=event_type,
                instance_id=instance_id,
                payload_hash=payload_hash,
                payload=payload,
                status="processing"
            )
            self.db.add(webhook_log)
        
        self.db.commit()
        
        # Process based on event type
        result = None
        
        if event_type in ["product.created", "product.created", "product.updated", "product.update"]:
            # Sync product to Odoo using instance configuration
            task_result = sync_product_to_odoo.apply_async(
                args=[payload, instance_id],
                retry=True,
                queue='sync_queue',
                headers={'parent_task_id': self.request.id}
            )
            
            logger.info(f"Queued product sync task {task_result.id} for product {payload.get('id')}")
            result = {"success": True, "action": "queued", "task_id": task_result.id}
            
        elif event_type in ["order.created", "order.created", "order.updated", "order.update"]:
            # Sync order to Odoo using instance configuration
            task_result = sync_order_to_odoo.apply_async(
                args=[payload, instance_id],
                retry=True,
                queue='sync_queue',
                headers={'parent_task_id': self.request.id}
            )
            
            logger.info(f"Queued order sync task {task_result.id} for order {payload.get('id')}")
            result = {"success": True, "action": "queued", "task_id": task_result.id}
            
        elif event_type == "product.deleted":
            # Archive product in Odoo
            logger.info(f"Product deleted: {payload.get('id')}")
            result = {"success": True, "action": "deleted"}
            
        else:
            logger.warning(f"Unhandled event type: {event_type}")
            result = {"success": True, "action": "ignored", "message": "Event type not handled"}
        
        # Update webhook log
        webhook_log.status = "completed" if result.get("success") else "failed"
        webhook_log.processed_at = datetime.utcnow()
        webhook_log.error_message = result.get("error") if not result.get("success") else None
        self.db.commit()
        
        logger.info(f"Webhook {event_id} processed successfully")
        
        return {
            "success": True,
            "event_id": event_id,
            "event_type": event_type,
            "result": result
        }
        
    except Exception as exc:
        logger.error(f"Error processing webhook {event_id}: {exc}")
        
        # Update webhook log on error
        if 'webhook_log' in locals():
            webhook_log.status = "failed"
            webhook_log.error_message = str(exc)
            self.db.commit()
        
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.webhook_tasks.cleanup_old_webhooks",
    max_retries=1
)
def cleanup_old_webhooks(self, days: int = 30) -> Dict[str, Any]:
    """
    Clean up webhook logs older than specified days.
    
    Args:
        days: Number of days to keep logs
        
    Returns:
        Dict with cleanup statistics
    """
    try:
        from datetime import timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        deleted_count = self.db.query(WebhookLog).filter(
            WebhookLog.created_at < cutoff_date,
            WebhookLog.status == "completed"
        ).delete()
        
        self.db.commit()
        
        logger.info(f"Cleaned up {deleted_count} old webhook logs")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Error cleaning up webhooks: {exc}")
        return {
            "success": False,
            "error": str(exc)
        }
