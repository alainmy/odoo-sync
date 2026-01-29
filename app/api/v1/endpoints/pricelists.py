"""API endpoints for pricelist management."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.pricelist_schemas import (
    PricelistSyncCreate,
    PricelistSyncUpdate,
    PricelistSyncResponse,
    ProductPriceUpdate,
    BulkPriceSyncRequest,
    BulkPriceSyncResponse,
    PriceSyncResult,
    OdooPricelist
)
from app.repositories.pricelist_sync_repository import PricelistSyncRepository
from app.services.pricelist_service import PricelistService
from app.crud.odoo import OdooClient
from app.models.admin import WooCommerceInstance
from app.core.config import settings
from app.tasks.sync_helpers import create_wc_api_client
from app.tasks.pricelist_tasks import (
    sync_product_prices_task,
    sync_all_product_prices_task,
    fetch_odoo_pricelists_task
)
from app.api.v1.endpoints.odoo import get_session_id, get_odoo_from_active_instance

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# PRICELIST SYNC CONFIGURATION ENDPOINTS
# ============================================================================

@router.get("/config", response_model=List[PricelistSyncResponse])
def get_pricelist_configs(
    instance_id: int,
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get all pricelist sync configurations for an instance.
    
    Args:
        instance_id: WooCommerce instance ID
        active_only: Return only active configs
        db: Database session
    """
    repo = PricelistSyncRepository(db)
    
    if active_only:
        configs = repo.get_active_by_instance(instance_id)
    else:
        configs = repo.get_all_by_instance(instance_id)
    
    return configs


@router.get("/config/{config_id}", response_model=PricelistSyncResponse)
def get_pricelist_config(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific pricelist sync configuration."""
    repo = PricelistSyncRepository(db)
    config = repo.get_by_id(config_id)
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pricelist config {config_id} not found"
        )
    
    return config


@router.post("/config", response_model=PricelistSyncResponse, status_code=status.HTTP_201_CREATED)
def create_pricelist_config(
    config: PricelistSyncCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new pricelist sync configuration.
    
    Args:
        config: Pricelist configuration data
        db: Database session
    """
    repo = PricelistSyncRepository(db)
    
    # Check if already exists
    existing = repo.get_by_odoo_pricelist(config.odoo_pricelist_id, config.instance_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pricelist {config.odoo_pricelist_id} already configured for instance {config.instance_id}"
        )
    
    # Validate price_type and meta_key
    if config.price_type == 'meta' and not config.meta_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meta_key is required when price_type is 'meta'"
        )
    
    new_config = repo.create(config)
    if not new_config:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create pricelist configuration"
        )
    
    return new_config


@router.put("/config/{config_id}", response_model=PricelistSyncResponse)
def update_pricelist_config(
    config_id: int,
    update_data: PricelistSyncUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a pricelist sync configuration.
    
    Args:
        config_id: Pricelist config ID
        update_data: Data to update
        db: Database session
    """
    repo = PricelistSyncRepository(db)
    
    # Validate meta_key if price_type is meta
    if update_data.price_type == 'meta' and not update_data.meta_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meta_key is required when price_type is 'meta'"
        )
    
    updated_config = repo.update(config_id, update_data)
    if not updated_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pricelist config {config_id} not found"
        )
    
    return updated_config


@router.delete("/config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pricelist_config(
    config_id: int,
    db: Session = Depends(get_db)
):
    """Delete a pricelist sync configuration."""
    repo = PricelistSyncRepository(db)
    
    if not repo.delete(config_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pricelist config {config_id} not found"
        )
    
    return None


# ============================================================================
# ODOO PRICELIST ENDPOINTS
# ============================================================================

@router.get("/odoo/pricelists", response_model=List[OdooPricelist])
async def get_odoo_pricelists(
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
):
    """
    Fetch all active pricelists from Odoo.
    Useful for populating dropdown selections in UI.
    """
    try:
        pricelists = odoo.search_read_sync(
            'product.pricelist',
            domain=[('active', '=', True)],
            fields=['id', 'name', 'currency_id', 'active']
        )
        
        return pricelists
        
    except Exception as e:
        logger.error(f"Error fetching Odoo pricelists: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching Odoo pricelists: {str(e)}"
        )


# ============================================================================
# PRICE SYNC ENDPOINTS
# ============================================================================

@router.post("/sync/product", response_model=PriceSyncResult)
async def sync_product_prices(
    request: ProductPriceUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sync prices for a single product (async with Celery).
    
    Args:
        request: Product price update request
        background_tasks: FastAPI background tasks
        db: Database session
    """
    # Get instance for config
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == request.instance_id
    ).first()
    
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {request.instance_id} not found"
        )
    
    # Prepare configs from instance
    odoo_config = {
        "url": instance.odoo_url,
        "db": instance.odoo_db,
        "username": instance.odoo_username,
        "password": instance.odoo_password
    }
    wc_config = {
        "url": instance.woocommerce_url,
        "consumer_key": instance.woocommerce_consumer_key,
        "consumer_secret": instance.woocommerce_consumer_secret
    }
    
    # Trigger Celery task
    task = sync_product_prices_task.apply_async(
        args=[request.odoo_product_id, request.instance_id],
        kwargs={
            "odoo_config": odoo_config,
            "wc_config": wc_config
        }
    )
    
    logger.info(
        f"Price sync task started for product {request.odoo_product_id}: {task.id}"
    )
    
    return PriceSyncResult(
        odoo_product_id=request.odoo_product_id,
        woocommerce_id=None,
        success=True,
        synced_prices={},
        message=f"Price sync task started: {task.id}"
    )


@router.post("/sync/product/immediate", response_model=PriceSyncResult)
async def sync_product_prices_immediate(
    request: ProductPriceUpdate,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance)
):
    """
    Sync prices for a single product immediately (synchronous).
    
    Args:
        request: Product price update request
        db: Database session
    """
    try:
        # Get instance for config
        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == request.instance_id
        ).first()
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {request.instance_id} not found"
            )
        
        # Prepare WooCommerce config
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret
        }
        
        wcapi = create_wc_api_client(wc_config)
        
        service = PricelistService(db)
        result = service.sync_product_prices(
            odoo,
            request.odoo_product_id,
            request.instance_id,
            wcapi
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error syncing product prices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error syncing prices: {str(e)}"
        )


@router.post("/sync/bulk")
async def sync_bulk_prices(
    request: BulkPriceSyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sync prices for multiple products (async with Celery).
    
    Args:
        request: Bulk price sync request
        background_tasks: FastAPI background tasks
        db: Database session
    """
    # Get instance for config
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == request.instance_id
    ).first()
    
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {request.instance_id} not found"
        )
    
    # Prepare configs from instance
    odoo_config = {
        "url": instance.odoo_url,
        "db": instance.odoo_db,
        "username": instance.odoo_username,
        "password": instance.odoo_password
    }
    wc_config = {
        "url": instance.woocommerce_url,
        "consumer_key": instance.woocommerce_consumer_key,
        "consumer_secret": instance.woocommerce_consumer_secret
    }
    
    # Trigger Celery task
    task = sync_all_product_prices_task.apply_async(
        args=[request.instance_id, request.product_ids],
        kwargs={
            "odoo_config": odoo_config,
            "wc_config": wc_config
        }
    )
    
    logger.info(
        f"Bulk price sync task started for instance {request.instance_id}: {task.id}"
    )
    
    return {
        "task_id": task.id,
        "status": "started",
        "message": f"Bulk price sync task started for instance {request.instance_id}"
    }


@router.post("/sync/bulk/immediate", response_model=BulkPriceSyncResponse)
async def sync_bulk_prices_immediate(
    request: BulkPriceSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance)
):
    """
    Sync prices for multiple products immediately (synchronous).
    Use with caution for large product sets.
    
    Args:
        request: Bulk price sync request
        db: Database session
    """
    try:
        # Get instance for config
        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == request.instance_id
        ).first()
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {request.instance_id} not found"
            )
        
        # Prepare WooCommerce config
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret
        }
        
        wcapi = create_wc_api_client(wc_config)
        
        service = PricelistService(db)
        results = service.sync_all_product_prices(
            odoo,
            request.instance_id,
            request.product_ids,
            wcapi
        )
        
        return BulkPriceSyncResponse(
            total_products=results['total'],
            successful=results['successful'],
            failed=results['failed'],
            results=results['details']
        )
        
    except Exception as e:
        logger.error(f"Error in bulk price sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error syncing bulk prices: {str(e)}"
        )
