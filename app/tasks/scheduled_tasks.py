"""
Scheduled Celery tasks for automatic synchronization.
"""
import logging
from typing import Dict, Any
from celery import Task
from celery.schedules import crontab
from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.tasks.sync_tasks import full_product_sync_wc_to_odoo
from app.tasks.webhook_tasks import cleanup_old_webhooks
from app.tasks.task_logger import log_celery_task
from app.tasks.task_monitoring import cleanup_old_task_logs
from app.repositories.instance_repository import InstanceRepository
from app.core.alerts import alert_manager, send_task_error_alert

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


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.scheduled_tasks.schedule_multi_instance_product_sync"
)
@log_celery_task
def schedule_multi_instance_product_sync(self) -> Dict[str, Any]:
    """
    Scheduled task to trigger product sync for all active instances.
    Iterates through all users' active instances and queues individual
    sync tasks. Runs every 15 minutes (configured in celery_app.py).
    
    Returns:
        Dict with scheduling statistics
    """
    try:
        logger.info("Starting multi-instance product sync scheduler")
        
        # Get repository
        instance_repo = InstanceRepository(self.db)
        
        # Get all active instances with auto_sync enabled
        active_instances = instance_repo.get_active_instances()
        
        total_instances = len(active_instances)
        queued_count = 0
        skipped_count = 0
        error_count = 0
        task_ids = []
        
        logger.info(f"Found {total_instances} active instances")
        
        for instance in active_instances:
            try:
                # Check if auto_sync_products is enabled for this instance
                if not instance.auto_sync_products:
                    logger.debug(
                        f"Skipping instance {instance.id} ({instance.name}): "
                        f"auto_sync_products is disabled"
                    )
                    skipped_count += 1
                    continue
                
                # Build instance-specific configurations
                odoo_config = {
                    "url": instance.odoo_url,
                    "db": instance.odoo_db,
                    "username": instance.odoo_username,
                    "password": instance.odoo_password,
                }
                
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret,
                }
                
                # Validate configurations
                if not all([odoo_config["url"], odoo_config["db"],
                           odoo_config["username"],
                           odoo_config["password"]]):
                    logger.warning(
                        f"Skipping instance {instance.id} "
                        f"({instance.name}): Incomplete Odoo config"
                    )
                    skipped_count += 1
                    continue
                
                if not all([wc_config["url"],
                           wc_config["consumer_key"],
                           wc_config["consumer_secret"]]):
                    logger.warning(
                        f"Skipping instance {instance.id} "
                        f"({instance.name}): Incomplete WC config"
                    )
                    skipped_count += 1
                    continue
                
                # Queue sync task for this instance
                result = full_product_sync_wc_to_odoo.apply_async(
                    kwargs={
                        "instance_id": instance.id,
                        "odoo_config": odoo_config,
                        "wc_config": wc_config
                    },
                    headers={"parent_task_id": self.request.id}
                )
                
                task_ids.append({
                    "instance_id": instance.id,
                    "instance_name": instance.name,
                    "task_id": result.id
                })
                
                queued_count += 1
                logger.info(
                    f"Queued sync for instance {instance.id} "
                    f"({instance.name}): task_id={result.id}"
                )
                
            except Exception as e:
                error_count += 1
                logger.error(
                    f"Error queuing sync for instance {instance.id} "
                    f"({instance.name}): {e}",
                    exc_info=True
                )
                # Send alert for critical errors
                send_task_error_alert(
                    task_name='schedule_multi_instance_product_sync',
                    error=e,
                    task_id=self.request.id,
                    instance_id=instance.id,
                    retries=0,
                    max_retries=1
                )
        
        logger.info(
            f"Multi-instance sync scheduling completed: "
            f"{queued_count} queued, {skipped_count} skipped, "
            f"{error_count} errors"
        )
        
        return {
            "success": True,
            "total_instances": total_instances,
            "queued": queued_count,
            "skipped": skipped_count,
            "errors": error_count,
            "task_ids": task_ids
        }
        
    except Exception as exc:
        logger.error(
            f"Error in multi-instance sync scheduler: {exc}",
            exc_info=True
        )
        return {
            "success": False,
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.scheduled_tasks.auto_sync_stock"
)
@log_celery_task
def auto_sync_stock(self) -> Dict[str, Any]:
    """
    Scheduled task to sync stock levels from Odoo to WooCommerce.
    Runs every 30 minutes (configured in celery_app.py beat_schedule).
    
    Returns:
        Dict with sync result
    """
    try:
        logger.info("Starting automatic stock sync")
        
        from app.crud.odoo import OdooClient
        from app.services.woocommerce import wc_request
        
        # Initialize Odoo client
        client = OdooClient(
            settings.odoo_url,
            settings.odoo_db,
            settings.odoo_username,
            settings.odoo_password
        )
        
        # Get products with stock information
        products = client.search_read_sync(
            "product.product",
            domain=[("default_code", "!=", False), ("active", "=", True)],
            fields=["id", "default_code", "qty_available"]
        )
        
        updated_count = 0
        error_count = 0
        
        for product in products:
            try:
                sku = product.get("default_code")
                qty = int(product.get("qty_available", 0))
                
                # Find WooCommerce product by SKU
                wc_products = wc_request("GET", "/products", params={"sku": sku})
                
                if wc_products:
                    wc_product_id = wc_products[0]["id"]
                    
                    # Update stock in WooCommerce
                    wc_request(
                        "PUT",
                        f"/products/{wc_product_id}",
                        params={"stock_quantity": qty}
                    )
                    
                    updated_count += 1
                    
            except Exception as e:
                logger.error(f"Error syncing stock for SKU {sku}: {e}")
                error_count += 1
        
        logger.info(
            f"Stock sync completed: {updated_count} updated, {error_count} errors"
        )
        
        return {
            "success": True,
            "updated_count": updated_count,
            "error_count": error_count
        }
        
    except Exception as exc:
        logger.error(f"Error in automatic stock sync: {exc}")
        return {
            "success": False,
            "error": str(exc)
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.scheduled_tasks.cleanup_logs"
)
def cleanup_logs(self) -> Dict[str, Any]:
    """
    Scheduled task to clean up old logs.
    Runs daily at midnight.
    
    Returns:
        Dict with cleanup result
    """
    try:
        logger.info("Starting log cleanup")
        
        # Clean up webhook logs older than 30 days
        webhook_result = cleanup_old_webhooks.apply_async(
            args=[30]
        ).get(timeout=60)
        
        # Could add cleanup for other logs here
        
        logger.info("Log cleanup completed")
        
        # Clean up old task logs (older than 30 days)
        task_log_result = cleanup_old_task_logs(days=30)
        
        return {
            "success": True,
            "webhook_cleanup": webhook_result,
            "task_log_cleanup": task_log_result
        }
        
    except Exception as exc:
        logger.error(f"Error in log cleanup: {exc}")
        return {
            "success": False,
            "error": str(exc)
        }


# Placeholder for the implementation of the selected task
# This section will be updated with the actual implementation logic.


# Configure additional periodic tasks
@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """
    Setup additional periodic tasks after Celery is initialized.
    """
    # Clean up logs daily at midnight
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        cleanup_logs.s(),
        name='cleanup-logs-daily'
    )
