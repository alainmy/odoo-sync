"""
Sync Management endpoints for Odoo-WooCommerce product synchronization.
"""
from uuid import uuid4
import requests
import os
import logging
from re import Match
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.db.session import get_db
from app.crud.odoo import OdooClient
from app.crud import crud_instance
from app.repositories import ProductSyncRepository
from app.core.config import settings
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.utils.instance_helpers import get_active_instance_id
from app.schemas.sync_schemas import (
    OdooProductListResponse,
    ProductSyncStatusResponse,
    BatchSyncRequest,
    BatchSyncResponse,
    SyncQueueResponse,
    SyncQueueItem,
    DetectChangesRequest,
    DetectChangesResponse,
    SyncStatisticsResponse
)
from app.tasks.sync_tasks import sync_product_to_woocommerce
from app.tasks.task_monitoring import create_task_response
from app.api.v1.endpoints.odoo import get_session_id, get_odoo_from_active_instance
from celery import group


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync-management", tags=["Sync Management"])


@router.get("/products", response_model=OdooProductListResponse)
async def list_odoo_products_with_sync_status(
    limit: int = Query(50, le=200, description="Number of products to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None,
        description="Filter by sync status: never_synced, synced, modified, error"
    ),
    search: Optional[str] = Query(
        None, description="Search by product name or SKU"),
    category_id: Optional[int] = Query(
        None, description="Filter by Odoo category ID"),
    request: Request = None,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    List Odoo products with their WooCommerce sync status.

    This endpoint:
    1. Fetches products from Odoo using JSON-RPC
    2. Enriches them with sync status from ProductSync table
    3. Calculates sync_status (never_synced, synced, modified, error)
    4. Applies filters and returns paginated results
    """
    try:
        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=301, detail="Failed to authenticate with Odoo")
        # Build Odoo domain for filtering
        domain = []
        if search:
            domain.append("|")
            domain.append(["name", "ilike", search])
            domain.append(["default_code", "ilike", search])
        if category_id:
            domain.append(["categ_id", "=", category_id])

        domain.append(["sale_ok", "=", True])
        # Fetch from Odoo (over-fetch to account for status filtering)
        # If filtering by status, we need more products since some will be filtered out
        fetch_limit = (offset - 1) * limit if offset > 1 else 0
        # fetch_limit = limit * 3 if filter_status else limit

        logger.info(
            f"Fetching products from Odoo: domain={domain}, limit={fetch_limit}")
        search_count = await odoo.search_count(
            uid,
            "product.template",
            domain=[["sale_ok", "=", True], ["purchase_ok", "=", False]]
        )
        product_count = search_count["result"]
        odoo_response = await odoo.search_read(
            uid,
            "product.template",
            domain=domain if domain else [],
            fields=[
                "id",
                "name",
                "default_code",  # SKU
                "list_price",
                "write_date",
                "active",
                "sale_ok",
                "categ_id",  # Categoría del producto
                "description",
                "description_sale",
                "type",
                "weight",
                "product_tag_ids",  # Tags del producto
                "attribute_line_ids",
                "product_variant_count"
            ],
            limit=fetch_limit,
            offset=offset
        )

        odoo_products = odoo_response.get("result", [])
        logger.info(f"Fetched {len(odoo_products)} products from Odoo")

        # Enrich with sync status
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = ProductSyncRepository(db)
        enriched_products, total_before_filter = sync_repo.get_products_with_sync_status(
            odoo_products,
            instance_id=instance_id,
            filter_status=filter_status
        )

        # Apply limit after filtering
        paginated_products = enriched_products[:limit]

        logger.info(
            f"Returning {len(paginated_products)} products after filtering")

        return OdooProductListResponse(
            total_count=total_before_filter,
            total=product_count,
            products=[ProductSyncStatusResponse(
                **p) for p in paginated_products],
            filters_applied={
                "status": filter_status,
                "search": search,
                "category_id": category_id,
                "limit": limit,
                "offset": offset
            }
        )
    except HTTPException as ex:
        logger.error(
            f"HTTPException in list_odoo_products_with_sync_status: {ex.detail}")
        raise
    except Exception as e:
        logger.error(
            f"Error fetching products with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching products: {str(e)}")




# @router.get("/download-image")
# def download_image(url: str):
#     result = download_and_save_image(url)
#     return result


@router.post("/products/batch-sync", response_model=BatchSyncResponse)
async def batch_sync_products(
    request_data: BatchSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue batch synchronization of products from Odoo to WooCommerce.

    This endpoint:
    1. Validates that Odoo products exist
    2. Marks them for sync (needs_sync=True)
    3. Fetches full product data from Odoo
    4. Queues Celery tasks for each product
    5. Returns task information
    """
    try:
        odoo_ids = request_data.odoo_ids
        logger.info(f"Starting batch sync for {len(odoo_ids)} products")

        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()

        # Fetch products from Odoo
        odoo_response = await odoo.search_read(
            uid,
            "product.template",
            domain=[["id", "in", odoo_ids]],
            fields=[
                "id",
                "name",
                "default_code",
                "list_price",
                "write_date",
                "description",
                "description_sale",
                "active",
                "sale_ok",
                "type",
                "categ_id",
                "product_tag_ids",
                "image_1920",
                "attribute_line_ids",
                "product_variant_count",
                "product_variant_id",
                "product_template_image_ids",
                "is_published",
                "weight"
            ],
            limit=len(odoo_ids)
        )

        products = odoo_response.get("result", [])

        if not products:
            raise HTTPException(
                status_code=404,
                detail=f"No products found in Odoo with IDs: {odoo_ids}"
            )

        logger.info(f"Found {len(products)} products in Odoo")

        # Mark products for sync in database
        instance_id = get_active_instance_id(db, current_user)

        # Obtener configuraciones de la instancia
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
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

        sync_repo = ProductSyncRepository(db)
        updated_count = sync_repo.mark_products_for_sync(odoo_ids, instance_id)
        logger.info(
            f"Marked {updated_count} existing sync records as needs_sync")

        # Queue Celery tasks
        tasks = []
        for product in products:
            # Convert product to dict and queue task
            # get url images
            task = sync_product_to_woocommerce.apply_async(
                args=[product, instance_id],
                kwargs={
                    "odoo_config": odoo_config,
                    "wc_config": wc_config,
                    "create_if_not_exists": request_data.create_if_not_exists,
                    "update_existing": request_data.update_existing,
                    "force_sync": request_data.force_sync
                },
                queue='sync_queue'
            )
            tasks.append({
                "odoo_id": product["id"],
                "name": product["name"],
                "task_id": task.id
            })

        logger.info(f"Queued {len(tasks)} Celery tasks")

        # Return consistent response for first task
        first_task_response = create_task_response(
            type('Task', (), {'id': tasks[0]["task_id"]}),
            instance_id
        ) if tasks else {}

        return BatchSyncResponse(
            task_id=tasks[0]["task_id"] if tasks else None,
            status="queued",
            total_products=len(tasks),
            message=f"Successfully queued {len(tasks)} products for sync to WooCommerce",
            results=tasks
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch sync: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Batch sync error: {str(e)}")


@router.get("/queue", response_model=SyncQueueResponse)
async def get_sync_queue(
    limit: int = Query(100, le=500, description="Maximum items to return"),
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get products that are marked for sync (needs_sync=True).
    """
    try:
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = ProductSyncRepository(db)
        products_needing_sync = sync_repo.get_products_needing_sync(
            instance_id=instance_id, limit=limit)

        if not products_needing_sync:
            return SyncQueueResponse(
                total_count=0,
                products=[]
            )

        # Fetch product details from Odoo
        uid = await odoo.odoo_authenticate()
        odoo_ids = [p.odoo_id for p in products_needing_sync]

        odoo_response = await odoo.search_read(
            uid,
            "product.template",
            domain=[["id", "in", odoo_ids]],
            fields=["id", "name", "default_code", "write_date"],
            limit=limit
        )

        products = odoo_response.get("result", [])
        product_map = {p["id"]: p for p in products}

        # Build queue items
        queue_items = []
        for sync in products_needing_sync:
            product = product_map.get(sync.odoo_id)
            if not product:
                continue

            # Determine reason
            reason = "never_synced"
            if sync.error:
                reason = "error_retry"
            elif sync.last_synced_at:
                reason = "modified"

            queue_items.append(SyncQueueItem(
                odoo_id=sync.odoo_id,
                name=product["name"],
                sku=product.get("default_code"),
                odoo_write_date=product.get("write_date"),
                last_synced_at=sync.last_synced_at,
                reason=reason,
                priority=5
            ))

        return SyncQueueResponse(
            total_count=len(queue_items),
            products=queue_items
        )

    except Exception as e:
        logger.error(f"Error getting sync queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect-changes", response_model=DetectChangesResponse)
async def detect_changes(
    request_data: DetectChangesRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance)
):
    """
    Detect products that have been modified in Odoo since last sync.
    """
    try:
        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()

        # Build domain for modified products
        domain = []
        if request_data.since:
            domain.append(["write_date", ">", request_data.since.isoformat()])

        # Fetch modified products
        odoo_response = await odoo.search_read(
            uid,
            "product.template",
            domain=domain,
            fields=["id", "name", "default_code", "list_price", "write_date"],
            limit=request_data.limit
        )

        products = odoo_response.get("result", [])

        # Enrich with sync status
        sync_repo = ProductSyncRepository(db)
        enriched_products, total = sync_repo.get_products_with_sync_status(
            products,
            filter_status="modified" if request_data.only_modified else None
        )

        return DetectChangesResponse(
            total_modified=total,
            products=[ProductSyncStatusResponse(
                **p) for p in enriched_products]
        )

    except Exception as e:
        logger.error(f"Error detecting changes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", response_model=SyncStatisticsResponse)
async def get_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get sync statistics for the current user's active instance.
    Only shows data from the user's active instance.
    """
    try:
        instance_id = get_active_instance_id(db, current_user)
        from app.models.admin import ProductSync

        # Calculate statistics filtered by instance_id
        base_query = db.query(ProductSync).filter(
            ProductSync.instance_id == instance_id)

        total = base_query.count()
        never_synced = base_query.filter(
            ProductSync.last_synced_at == None).count()
        synced = base_query.filter(
            and_(ProductSync.last_synced_at != None, ProductSync.error == False)
        ).count()
        errors = base_query.filter(ProductSync.error == True).count()

        # Get last sync time for this instance
        last_sync_record = base_query.filter(
            ProductSync.last_synced_at != None
        ).order_by(ProductSync.last_synced_at.desc()).first()

        return SyncStatisticsResponse(
            total_products=total,
            never_synced=never_synced,
            synced=synced,
            modified=0,  # Would need to compare with Odoo
            errors=errors,
            last_sync=last_sync_record.last_synced_at if last_sync_record else None
        )

    except Exception as e:
        logger.error(f"Error getting statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
