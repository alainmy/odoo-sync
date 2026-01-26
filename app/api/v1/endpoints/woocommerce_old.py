"""
Updated WooCommerce endpoints with Celery task integration.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from celery.result import AsyncResult
import uuid
import time
import logging

from app.models.product_models import (
    OdooProduct,
    OdooToWooCommerceRequest,
    OdooToWooCommerceSyncResponse,
    ProductSyncResult,
    OdooCategory,
    OdooCategoriesToWooCommerceRequest,
    OdooCategoriesToWooCommerceSyncResponse,
)
from app.schemas.schemas import Product, SyncResult, BulkSyncRequest, BulkSyncResponse
from app.core.config import settings
from app.db.session import get_db
from app.repositories import ProductSyncRepository
from app.services.woocommerce import wc_request, odoo_product_to_woocommerce
from app.crud.admin import (
    save_product_sync,
    get_product_sync_by_odoo_id,
    update_product_sync,
    save_categroy_sync,
    get_categroy_by_odoo_id,
    update_categroy_sync
)
from app.crud.category_sync import get_categories_map
from app.schemas.admin import ProductSyncCreate, CategorySyncCreate

# Import Celery tasks
from app.tasks.sync_tasks import (
    sync_product_to_odoo,
    sync_product_to_woocommerce,
    full_product_sync_wc_to_odoo
)
from app.services.woocommerce import (
    create_or_update_woocommerce_product,
    create_or_update_woocommerce_category
)

router = APIRouter(prefix="/woocommerce", tags=["woocommerce"])
_logger = logging.getLogger(__name__)


# ==================== Product Endpoints ====================

@router.get("/products", response_model=List[Product])
def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None
):
    """List WooCommerce products with pagination."""
    params = {"page": page, "per_page": per_page}
    if status:
        params["status"] = status
    
    data = wc_request("GET", "/products", params=params)
    return [
        Product(
            id=p["id"],
            name=p.get("name"),
            sku=p.get("sku"),
            price=p.get("price"),
            status=p.get("status"),
            type=p.get("type"),
        )
        for p in data
    ]


@router.post("/products/sync/{product_id}", response_model=Dict[str, Any])
def sync_single_product_to_odoo(product_id: int):
    """
    Sync a single WooCommerce product to Odoo using Celery task.
    Returns task ID for status tracking.
    """
    try:
        # Get product data from WooCommerce
        product_data = wc_request("GET", f"/products/{product_id}")
        
        # Queue Celery task
        task = sync_product_to_odoo.apply_async(args=[product_data])
        
        return {
            "task_id": task.id,
            "status": "queued",
            "product_id": product_id,
            "message": "Product sync task queued"
        }
        
    except Exception as e:
        _logger.error(f"Error queuing product sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/products/sync", response_model=Dict[str, Any])
def bulk_sync_products_to_odoo(body: BulkSyncRequest):
    """
    Bulk sync WooCommerce products to Odoo using Celery tasks.
    Returns list of task IDs for status tracking.
    """
    task_ids = []
    
    for product_id in body.product_ids:
        try:
            # Get product data from WooCommerce
            product_data = wc_request("GET", f"/products/{product_id}")
            
            # Queue Celery task
            task = sync_product_to_odoo.apply_async(args=[product_data])
            task_ids.append({
                "product_id": product_id,
                "task_id": task.id
            })
            
        except Exception as e:
            _logger.error(f"Error queuing product {product_id}: {e}")
            task_ids.append({
                "product_id": product_id,
                "error": str(e)
            })
    
    return {
        "total": len(body.product_ids),
        "tasks": task_ids,
        "message": "Bulk sync tasks queued"
    }


@router.post("/products/full-sync")
def full_product_sync():
    """
    Trigger full product catalog sync from WooCommerce to Odoo.
    Uses Celery for async processing.
    """
    task = full_product_sync_wc_to_odoo.apply_async()
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Full product sync task queued. Use /sync/status/{task_id} to check progress"
    }


@router.get("/sync/status/{task_id}")
def get_sync_task_status(task_id: str):
    """
    Check the status of a Celery sync task.
    Returns task state, progress, and result if completed.
    """
    task_result = AsyncResult(task_id)
    
    response = {
        "task_id": task_id,
        "status": task_result.state,
        "ready": task_result.ready(),
    }
    
    if task_result.state == 'PENDING':
        response["message"] = "Task is waiting to be executed"
    elif task_result.state == 'STARTED':
        response["message"] = "Task has started"
    elif task_result.state == 'PROGRESS':
        response["current"] = task_result.info.get('current', 0)
        response["status_message"] = task_result.info.get('status', '')
    elif task_result.state == 'SUCCESS':
        response["result"] = task_result.result
        response["message"] = "Task completed successfully"
    elif task_result.state == 'FAILURE':
        response["error"] = str(task_result.info)
        response["message"] = "Task failed"
    
    return response


@router.post("/products/sync-from-odoo",
             response_model=OdooToWooCommerceSyncResponse)
async def sync_products_from_odoo(
    request: OdooToWooCommerceRequest,
    db: Session = Depends(get_db)
):
    """
    Sync products from Odoo to WooCommerce.
    This endpoint processes products synchronously for immediate feedback.
    For large batches, consider using the async endpoint.
    """
    start_time = time.time()
    
    results = []
    counters = {
        "successful": 0,
        "failed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0
    }
    
    for odoo_product in request.products:
        try:
            # Convert Odoo product to WooCommerce format
            wc_product_data = await odoo_product_to_woocommerce(
                odoo_product,
                request.default_status
            )
            
            # Create or update in WooCommerce
            result = await create_or_update_woocommerce_product(
                odoo_product=odoo_product,
                wc_product_data=wc_product_data,
                create_if_not_exists=request.create_if_not_exists,
                update_existing=request.update_existing,
                db=db
            )
            
            # Save sync record
            if result.success and result.woocommerce_id:
                existing_sync = get_product_sync_by_odoo_id(db, odoo_product.id)
                
                sync_data = ProductSyncCreate(
                    odoo_id=odoo_product.id,
                    woocommerce_id=result.woocommerce_id,
                    created=(result.action == "created"),
                    updated=(result.action == "updated"),
                    skipped=(result.action == "skipped"),
                    error=not result.success,
                    message=result.message,
                    error_details=result.error_details or ""
                )
                
                if existing_sync:
                    update_product_sync(db, existing_sync.id, sync_data)
                else:
                    save_product_sync(db, sync_data)
            
            results.append(result)
            
            # Update counters
            if result.success:
                counters["successful"] += 1
                if result.action == "created":
                    counters["created"] += 1
                elif result.action == "updated":
                    counters["updated"] += 1
                elif result.action == "skipped":
                    counters["skipped"] += 1
            else:
                counters["failed"] += 1
                
        except Exception as e:
            _logger.error(f"Error syncing product {odoo_product.id}: {e}")
            results.append(ProductSyncResult(
                odoo_id=odoo_product.id,
                odoo_sku=odoo_product.default_code,
                success=False,
                action="error",
                message=str(e),
                error_details=str(e)
            ))
            counters["failed"] += 1
    
    execution_time = time.time() - start_time
    
    return OdooToWooCommerceSyncResponse(
        total_processed=len(request.products),
        successful=counters["successful"],
        failed=counters["failed"],
        created=counters["created"],
        updated=counters["updated"],
        skipped=counters["skipped"],
        results=results,
        execution_time_seconds=execution_time
    )


@router.post("/products/sync-from-odoo-async")
async def sync_products_from_odoo_async(
    request: OdooToWooCommerceRequest,
    db: Session = Depends(get_db)
):
    """
    Async version: Queue Celery tasks for each Odoo product.
    Recommended for large batches.
    """
    task_ids = []
    
    for odoo_product in request.products:
        # Convert to dict for Celery serialization
        product_data = odoo_product.dict()
        
        # Queue task
        task = sync_product_to_woocommerce.apply_async(
            args=[product_data, request.create_if_not_exists, request.update_existing]
        )
        
        task_ids.append({
            "odoo_id": odoo_product.id,
            "task_id": task.id
        })
    
    return {
        "total": len(request.products),
        "tasks": task_ids,
        "message": "Product sync tasks queued. Use /sync/status/{task_id} to check each task"
    }


# ==================== Category Endpoints ====================

@router.post("/categories/sync-from-odoo",
             response_model=OdooCategoriesToWooCommerceSyncResponse)
async def sync_categories_from_odoo(
    request: OdooCategoriesToWooCommerceRequest,
    db: Session = Depends(get_db)
):
    """
    Sync categories from Odoo to WooCommerce.
    Handles parent-child relationships.
    """
    start_time = time.time()
    
    results = []
    counters = {
        "successful": 0,
        "failed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0
    }
    
    # Build categories map for parent relationships
    categories_map = await get_categories_map(db)
    
    # Sort categories to process parents first
    sorted_categories = sorted(
        request.categories,
        key=lambda cat: 0 if not cat.parent_id else 1
    )
    
    for odoo_category in sorted_categories:
        try:
            from app.models.product_models import WooCommerceCategoryCreate
            
            # Create WooCommerce category data
            wc_category_data = WooCommerceCategoryCreate(
                name=odoo_category.name,
                slug=odoo_category.name.lower().replace(" ", "-")
            )
            
            # Create or update in WooCommerce
            result = await create_or_update_woocommerce_category(
                odoo_category=odoo_category,
                wc_category_data=wc_category_data,
                create_if_not_exists=request.create_if_not_exists,
                update_existing=request.update_existing,
                categories_map=categories_map
            )
            
            # Save sync record
            if result.success and result.woocommerce_id:
                # Update categories map
                categories_map[odoo_category.id] = result.woocommerce_id
                
                existing_sync = get_categroy_by_odoo_id(db, odoo_category.id)
                
                sync_data = CategorySyncCreate(
                    odoo_id=odoo_category.id,
                    woocommerce_id=result.woocommerce_id,
                    created=(result.action == "created"),
                    updated=(result.action == "updated"),
                    skipped=(result.action == "skipped"),
                    error=not result.success,
                    message=result.message,
                    error_details=result.error_details or ""
                )
                
                if existing_sync:
                    update_categroy_sync(db, existing_sync.id, sync_data)
                else:
                    save_categroy_sync(db, sync_data)
            
            results.append(result)
            
            # Update counters
            if result.success:
                counters["successful"] += 1
                if result.action == "created":
                    counters["created"] += 1
                elif result.action == "updated":
                    counters["updated"] += 1
                elif result.action == "skipped":
                    counters["skipped"] += 1
            else:
                counters["failed"] += 1
                
        except Exception as e:
            _logger.error(f"Error syncing category {odoo_category.id}: {e}")
            from app.models.product_models import CategorySyncResult
            results.append(CategorySyncResult(
                odoo_id=odoo_category.id,
                odoo_name=odoo_category.name,
                success=False,
                action="error",
                message=str(e),
                error_details=str(e)
            ))
            counters["failed"] += 1
    
    execution_time = time.time() - start_time
    
    return OdooCategoriesToWooCommerceSyncResponse(
        total_processed=len(request.categories),
        successful=counters["successful"],
        failed=counters["failed"],
        created=counters["created"],
        updated=counters["updated"],
        skipped=counters["skipped"],
        results=results,
        execution_time_seconds=execution_time
    )


# ==================== Statistics Endpoints ====================

@router.get("/sync/stats")
async def get_sync_statistics(
    db: Session = Depends(get_db),
    repo: SyncRepository = Depends(get_sync_repository)
):
    """
    Get synchronization statistics for products, categories, and webhooks.
    """
    product_stats = repo.get_product_sync_statistics()
    webhook_stats = repo.get_webhook_statistics()
    
    return {
        "products": product_stats,
        "webhooks": webhook_stats,
        "message": "Sync statistics retrieved successfully"
    }
