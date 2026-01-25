"""Celery tasks for pricelist synchronization."""

import logging
from typing import Optional, List
from datetime import datetime
from celery import Task

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.pricelist_service import PricelistService
from app.crud.odoo import OdooClient
from app.core.config import settings
from app.tasks.sync_helpers import create_wc_api_client

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
    name="app.tasks.pricelist_tasks.sync_product_prices",
    max_retries=3,
    default_retry_delay=60
)
def sync_product_prices_task(
    self,
    odoo_product_id: int,
    instance_id: int,
    odoo_config: dict = None,
    wc_config: dict = None
):
    """
    Celery task to sync prices for a single product.
    
    Args:
        odoo_product_id: Odoo product ID
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)
    """
    db = SessionLocal()
    try:
        logger.info(
            f"Starting price sync for product {odoo_product_id}, "
            f"instance {instance_id}"
        )
        
        # Use provided config or fallback to settings
        if not odoo_config:
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }
        
        odoo_client = OdooClient(
            odoo_config["url"],
            odoo_config["db"],
            odoo_config["username"],
            odoo_config["password"]
        )
        wcapi = create_wc_api_client(wc_config)
        service = PricelistService(db)
        result = service.sync_product_prices(
            odoo_client,
            odoo_product_id,
            instance_id,
            wcapi
        )
        
        if result.success:
            logger.info(
                f"Successfully synced prices for product {odoo_product_id}: "
                f"{result.message}"
            )
            return {
                'success': True,
                'message': result.message,
                'synced_prices': result.synced_prices
            }
        else:
            logger.warning(
                f"Price sync failed for product {odoo_product_id}: "
                f"{result.message}"
            )
            return {
                'success': False,
                'message': result.message,
                'error': result.error_details
            }
                
    except Exception as e:
        logger.error(f"Error in price sync task for product {odoo_product_id}: {e}")
        # Retry the task
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.pricelist_tasks.sync_all_product_prices",
    max_retries=2
)
def sync_all_product_prices_task(
    self,
    instance_id: int,
    product_ids: Optional[List[int]] = None,
    odoo_config: dict = None,
    wc_config: dict = None
):
    """
    Celery task to sync prices for all products in an instance.
    
    Args:
        instance_id: WooCommerce instance ID
        product_ids: Optional list of specific product IDs
        odoo_config: Odoo configuration dict (url, db, username, password)
        wc_config: WooCommerce configuration dict (url, consumer_key, consumer_secret)
    """
    db = SessionLocal()
    try:
        logger.info(
            f"[PRICELIST TASK] Starting bulk price sync for instance {instance_id}, "
            f"products: {product_ids or 'all'}"
        )
        logger.info(f"[PRICELIST TASK] Odoo config present: {odoo_config is not None}")
        logger.info(f"[PRICELIST TASK] WC config present: {wc_config is not None}")
        
        # Use provided config or fallback to settings
        if not odoo_config:
            logger.info("[PRICELIST TASK] Using default Odoo config from settings")
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }
        
        odoo_client = OdooClient(
            odoo_config["url"],
            odoo_config["db"],
            odoo_config["username"],
            odoo_config["password"]
        )
        logger.info("[PRICELIST TASK] OdooClient created successfully")
        
        wcapi = create_wc_api_client(wc_config)
        logger.info("[PRICELIST TASK] WooCommerce API client created successfully")
        
        service = PricelistService(db)
        logger.info("[PRICELIST TASK] PricelistService created, calling sync_all_product_prices")
        
        results = service.sync_all_product_prices(
            odoo_client,
            instance_id,
            product_ids,
            wcapi
        )
        
        logger.info(
            f"[PRICELIST TASK] Bulk price sync completed for instance {instance_id}: "
            f"Total: {results['total']}, "
            f"{results['successful']} successful, {results['failed']} failed"
        )
        
        return results.model_dump()
            
    except Exception as e:
        logger.error(f"Error in bulk price sync task for instance {instance_id}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.pricelist_tasks.scheduled_price_sync"
)
def scheduled_price_sync_task(self):
    """
    Scheduled task to sync prices for all products in all active instances.
    Can be configured in Celery Beat.
    """
    db = SessionLocal()
    try:
        logger.info("Running scheduled price sync for all instances")
        
        # Get all active instances
        from app.models.admin import WooCommerceInstance
        instances = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.active == True
        ).all()
        
        for instance in instances:
            logger.info(f"Syncing prices for instance {instance.id}")
            
            # Prepare configs
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }
            wc_config = {
                "url": instance.woocommerce_url,
                "consumer_key": instance.woocommerce_consumer_key,
                "consumer_secret": instance.woocommerce_consumer_secret
            }
            
            sync_all_product_prices_task.delay(
                instance.id,
                odoo_config=odoo_config,
                wc_config=wc_config
            )
        
        logger.info(f"Scheduled price sync queued for {len(instances)} instances")
        return {'success': True, 'instances': len(instances)}
        
    except Exception as e:
        logger.error(f"Error starting scheduled price sync: {e}")
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.pricelist_tasks.fetch_odoo_pricelists")
def fetch_odoo_pricelists_task(odoo_config: dict = None):
    """
    Fetch all active pricelists from Odoo.
    Useful for populating pricelist selection in UI.
    
    Args:
        odoo_config: Odoo configuration dict (url, db, username, password)
        
    Returns:
        List of pricelists from Odoo
    """
    try:
        logger.info("Fetching pricelists from Odoo")
        
        # Use provided config or fallback to settings
        if not odoo_config:
            odoo_config = {
                "url": settings.odoo_url,
                "db": settings.odoo_db,
                "username": settings.odoo_username,
                "password": settings.odoo_password
            }
        
        odoo_client = OdooClient(
            odoo_config["url"],
            odoo_config["db"],
            odoo_config["username"],
            odoo_config["password"]
        )
        pricelists = odoo_client.search_read_sync(
            'product.pricelist',
            domain=[('active', '=', True)],
            fields=['id', 'name', 'currency_id', 'active']
        )
        
        logger.info(f"Found {len(pricelists)} active pricelists in Odoo")
        return pricelists
        
    except Exception as e:
        logger.error(f"Error fetching Odoo pricelists: {e}")
        return []
