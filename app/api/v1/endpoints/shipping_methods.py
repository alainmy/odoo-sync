from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.services.woocommerce import (
    create_or_update_woocommerce_shipping_method,
    find_woocommerce_shipping_zone_by_name,
    find_woocommerce_shipping_zone_by_id,
    find_woocommerce_shipping_method_in_zone,
    find_woocommerce_shipping_method_by_name_in_zone
)
from app.repositories import ShippingMethodRepository
from app.db.session import get_db
from app.core.config import settings
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shipping-methods", tags=["shipping-methods"])

# In-memory task tracking (similar to products endpoint)
SHIPPING_TASKS = {}


@router.get("/", response_model=List[Dict])
def list_shipping_methods(
    zone_name: Optional[str] = Query(None, description="Filter by shipping zone name"),
    zone_id: Optional[int] = Query(None, description="Filter by shipping zone ID"),
    method_name: Optional[str] = Query(None, description="Filter by shipping method name"),
    method_id: Optional[int] = Query(None, description="Filter by shipping method ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page")
):
    """
    List shipping methods from WooCommerce with optional filtering.
    """
    try:
        # Get WooCommerce API client
        # This would need to be implemented similar to other endpoints
        # For now, returning empty list as placeholder
        return []
    except Exception as e:
        logger.error(f"Error listing shipping methods: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/zones", response_model=List[Dict])
def list_shipping_zones():
    """
    List all shipping zones from WooCommerce.
    """
    try:
        # This would need to be implemented similar to other endpoints
        # For now, returning empty list as placeholder
        return []
    except Exception as e:
        logger.error(f"Error listing shipping zones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-from-odoo")
def sync_shipping_methods_from_odoo(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Sync shipping methods from Odoo to WooCommerce using Celery.
    First lists Odoo shipping methods, then calls Celery task for synchronization.
    """
    # Get active instance for the current user
    try:
        from app.crud import instance as crud_instance
        instance = crud_instance.get_active_instance(db, user_id=current_user.id)
        if not instance:
            # If no active instance, get the first one
            instances = crud_instance.get_all_instances(db, limit=1)
            instance = instances[0] if instances else None
    except Exception as e:
        logger.warning(f"Could not get instance: {e}")
        instance = None
    
    if not instance:
        raise HTTPException(status_code=404, detail="No WooCommerce instance found")
    
    # List Odoo shipping methods (for logging/informational purposes)
    try:
        from app.crud.odoo import OdooClient
        import asyncio
        
        # Initialize Odoo client
        odoo_client = OdooClient(
            instance.odoo_url,
            instance.odoo_db,
            instance.odoo_username,
            instance.odoo_password
        )
        
        # Authenticate and get shipping methods
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            uid = loop.run_until_complete(odoo_client.odoo_authenticate())
            if not uid:
                logger.error("Could not authenticate with Odoo")
                # Continue anyway - the Celery task will handle authentication
                carrier_count = 0
            else:
                # Get delivery carriers from Odoo
                carriers_result = loop.run_until_complete(
                    odoo_client.search_read(
                        uid,
                        "delivery.carrier",
                        domain=[],
                        limit=1000,  # Reasonable limit
                        fields=["id", "name"]
                    )
                )
                
                if carriers_result.get("error"):
                    logger.error(f"Odoo error when fetching carriers: {carriers_result['error']['message']}")
                    carrier_count = 0
                else:
                    carriers = carriers_result.get("result", [])
                    carrier_count = len(carriers)
                    logger.info(f"Found {carrier_count} shipping methods in Odoo: {[c.get('name') for c in carriers[:5]]}{'...' if len(carriers) > 5 else ''}")
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Could not list Odoo shipping methods: {e}")
        carrier_count = 0
    
    task_id = str(uuid.uuid4())
    SHIPPING_TASKS[task_id] = {"status": "queued", "processed": 0}
    
    # Use Celery task instead of background task
    from app.tasks.sync_tasks import full_shipping_method_sync_odoo_to_woocommerce
    full_shipping_method_sync_odoo_to_woocommerce.delay(
        instance_id=instance.id,
        odoo_config=None,  # Will use defaults from instance
        wc_config=None     # Will use defaults from instance
    )
    
    return {"task_id": task_id, "status": "queued", "odoo_carrier_count": carrier_count}


@router.get("/sync/status/{task_id}")
def shipping_sync_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get status of a shipping method sync task.
    """
    task = SHIPPING_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/methods/sync/{odoo_carrier_id}")
def sync_single_shipping_method(
    odoo_carrier_id: int,
    zone_name: str = Query(..., description="Target shipping zone name"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Sync a single shipping method from Odoo to WooCommerce.
    """
    try:
        # This would need to be implemented
        # For now, returning success as placeholder
        return {
            "odoo_id": odoo_carrier_id,
            "success": True,
            "action": "processed",
            "message": "Shipping method sync initiated"
        }
    except Exception as e:
        logger.error(f"Error syncing shipping method {odoo_carrier_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))