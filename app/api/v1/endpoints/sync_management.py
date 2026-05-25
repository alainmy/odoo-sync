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
from app.models.admin import Admin, ProductSync
from app.models.payment_journal_sync import PaymentJournalSync
from app.utils.instance_helpers import get_active_instance, get_active_instance_id
from app.schemas.sync_schemas import (
    OdooProductListResponse,
    PaymentJournalCreate,
    PaymentJournalListResponse,
    ProductSyncStatusResponse,
    BatchSyncRequest,
    BatchSyncResponse,
    SyncQueueResponse,
    SyncQueueItem,
    DetectChangesRequest,
    DetectChangesResponse,
    SyncStatisticsResponse,
    OdooTaxListResponse,
    TaxSyncStatusResponse,
    BatchTaxSyncRequest,
    BatchTaxSyncResponse,
    TaxSyncStatisticsResponse,
    PaymentJournalSyncStatusResponse,
    OdooPaymentJournalListResponse,
    BatchPaymentJournalSyncRequest,
    BatchPaymentJournalSyncResponse,
    PaymentJournalSyncStatisticsResponse
)
from app.tasks.sync_tasks import sync_product_to_woocommerce, sync_tax_to_woocommerce
from app.repositories.tax_sync_repository import TaxSyncRepository
from app.repositories.payment_journal_sync_repository import PaymentJournalSyncRepository
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
    tag_ids: Optional[list] = Query(None, description="tags"),
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
        active_instance = get_active_instance(db, current_user)
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
        if tag_ids:
            domain.append(["product_tag_ids", "in", tag_ids])
        domain.append(["sale_ok", "=", True])
        domain.append(["website_id", "=", active_instance.website_id])
        # Fetch from Odoo (over-fetch to account for status filtering)
        # If filtering by status, we need more products since some will be filtered out
        # fetch_limit = offset
        # fetch_limit = limit * 3 if filter_status else limit

        logger.info(
            f"Fetching products from Odoo: domain={domain}, limit={limit}, offset={offset}")
        search_count = await odoo.search_count(
            uid,
            "product.template",
            domain=[["sale_ok", "=", True]]
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
            limit=limit,
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
            total_count=product_count,
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
                "weight",
                'public_categ_ids',
                "taxes_id",
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
            if instance.product_descriptions == "description_sale":
                product["description"] = product.pop("description_sale", "")
            product.update({
                "is_published": request_data.publish_product
                if request_data.publish_product is not None else False})
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
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        # Authenticate with Odoo
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="Failed to authenticate with Odoo"
            )

        # Get total count from Odoo using search (returns only IDs)
        search_response = await odoo_client.search_read(
            uid,
            "product.template",
            domain=[["sale_ok", "=", True]],
            fields=["id"],
            limit=10000,  # High limit to get all
            offset=0
        )
        total_in_odoo = len(search_response.get("result", []))

        # Calculate statistics filtered by instance_id
        base_query = db.query(ProductSync).filter(
            ProductSync.instance_id == instance.id)

        total = base_query.count()

        synced = base_query.filter(
            and_(ProductSync.last_synced_at != None, ProductSync.error == False)
        ).count()
        never_synced = total_in_odoo - synced
        errors = base_query.filter(ProductSync.error == True).count()

        # Get last sync time for this instance
        last_sync_record = base_query.filter(
            ProductSync.last_synced_at != None
        ).order_by(ProductSync.last_synced_at.desc()).first()

        return SyncStatisticsResponse(
            total_products=total_in_odoo,
            never_synced=never_synced,
            synced=synced,
            modified=0,  # Would need to compare with Odoo
            errors=errors,
            last_sync=last_sync_record.last_synced_at if last_sync_record else None
        )

    except Exception as e:
        logger.error(f"Error getting statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/taxes", response_model=OdooTaxListResponse)
async def list_odoo_taxes_with_sync_status(
    limit: int = Query(50, le=200, description="Number of taxes to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None,
        description="Filter by sync status: never_synced, synced, error"
    ),
    search: Optional[str] = Query(
        None, description="Search by tax name"),
    request: Request = None,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    List Odoo taxes with their WooCommerce sync status.
    """
    try:
        active_instance = get_active_instance(db, current_user)
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=301, detail="Failed to authenticate with Odoo")

        domain = [["type_tax_use", "=", "sale"],
                  ["amount_type", "=", "percent"],
                  ["active", "=", True]]
        if search:
            domain.append(["name", "ilike", search])

        search_count = await odoo.search_count(
            uid, "account.tax", domain=[
                ["type_tax_use", "=", "sale"],
                ["amount_type", "=", "percent"],
                ["active", "=", True]
            ]
        )
        tax_count = search_count["result"]

        odoo_response = await odoo.search_read(
            uid,
            "account.tax",
            domain=domain if domain else [],
            fields=[
                "id",
                "name",
                "amount",
                "description",
                "price_include",
                "type_tax_use",
                "active",
                "write_date",
                "country_id"
            ],
            limit=limit,
            offset=offset
        )

        odoo_taxes = odoo_response.get("result", [])
        logger.info(f"Fetched {len(odoo_taxes)} taxes from Odoo")

        instance_id = get_active_instance_id(db, current_user)
        sync_repo = TaxSyncRepository(db)
        enriched_taxes = sync_repo.get_taxes_with_sync_status(
            odoo_taxes,
            instance_id=instance_id,
            filter_status=filter_status
        )

        paginated_taxes = enriched_taxes

        return OdooTaxListResponse(
            total_count=tax_count,
            taxes=[TaxSyncStatusResponse(
                odoo_id=t.get("id"),
                name=t.get("name", ""),
                rate=float(t.get("amount", 0)) *
                100 if t.get("amount") else None,
                amount=t.get("amount"),
                odoo_description=t.get("description", "") if t.get(
                    "description") else None,
                price_include=t.get("price_include", False) if t.get(
                    "price_include") is not None else False,
                tax_scope="sales" if t.get("type_tax_use") == "sale" else "purchase" if t.get(
                    "type_tax_use") == "purchase" else None,
                sync_status=t.get("sync_status", "never_synced") if t.get(
                    "sync_status") else "never_synced",
                woocommerce_id=t.get("woocommerce_id", None) if t.get(
                    "woocommerce_id") else None,
                last_synced_at=t.get("last_synced_at", None) if t.get(
                    "last_synced_at") else None
            ) for t in paginated_taxes],
            filters_applied={
                "status": filter_status,
                "search": search,
                "limit": limit,
                "offset": offset
            }
        )
    except HTTPException as ex:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching taxes with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching taxes: {str(e)}")


@router.post("/taxes/batch-sync", response_model=BatchTaxSyncResponse)
async def batch_sync_taxes(
    request_data: BatchTaxSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue batch synchronization of taxes from Odoo to WooCommerce.
    """
    try:
        odoo_ids = request_data.odoo_ids
        logger.info(f"Starting batch sync for {len(odoo_ids)} taxes")

        uid = await odoo.odoo_authenticate()

        odoo_response = await odoo.search_read(
            uid,
            "account.tax",
            domain=[["id", "in", odoo_ids]],
            fields=[
                "id",
                "name",
                "amount",
                "description",
                "price_include",
                "type_tax_use",
                "active",
                "write_date",
                "country_id",
            ],
            limit=len(odoo_ids)
        )

        taxes = odoo_response.get("result", [])

        if not taxes:
            raise HTTPException(
                status_code=404,
                detail=f"No taxes found in Odoo with IDs: {odoo_ids}"
            )

        logger.info(f"Found {len(taxes)} taxes in Odoo")

        instance_id = get_active_instance_id(db, current_user)

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

        sync_repo = TaxSyncRepository(db)
        updated_count = sync_repo.mark_taxes_for_sync(odoo_ids, instance_id)
        logger.info(
            f"Marked {updated_count} existing sync records as needs_sync")

        tasks = []
        for tax in taxes:
            task = sync_tax_to_woocommerce.apply_async(
                args=[tax, instance_id],
                kwargs={
                    "odoo_config": odoo_config,
                    "wc_config": wc_config,
                    "create_if_not_exists": request_data.create_if_not_exists,
                    "update_existing": request_data.update_existing
                },
                queue='sync_queue'
            )
            tasks.append({
                "odoo_id": tax["id"],
                "name": tax["name"],
                "task_id": task.id
            })

        logger.info(f"Queued {len(tasks)} Celery tasks for tax sync")

        return BatchTaxSyncResponse(
            task_id=tasks[0]["task_id"] if tasks else None,
            status="queued",
            total_taxes=len(tasks),
            message=f"Successfully queued {len(tasks)} taxes for sync to WooCommerce",
            results=tasks
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch tax sync: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Batch tax sync error: {str(e)}")


@router.get("/taxes/statistics", response_model=TaxSyncStatisticsResponse)
async def get_tax_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get tax sync statistics for the current user's active instance.
    """
    try:
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        instance_id = instance.id if instance else None

        if not instance_id:
            raise HTTPException(
                status_code=404,
                detail="No active instance found"
            )

        sync_repo = TaxSyncRepository(db)
        stats = sync_repo.get_statistics(instance_id)

        return TaxSyncStatisticsResponse(
            total=stats["total"],
            synced=stats["synced"],
            never_synced=stats["never_synced"],
            errors=stats["errors"],
            last_sync=stats["last_sync"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tax statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payment-journals", response_model=PaymentJournalListResponse)
async def list_payment_journal(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    
    instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
    
    repo = PaymentJournalSyncRepository(db=db)
    payment_jpurnals = repo.get_all_by_instance(instance.id)
    
    return PaymentJournalListResponse(
        data=[
            PaymentJournalSyncStatusResponse(
                id=item.id,
                odoo_journal_id=item.odoo_journal_id,
                odoo_journal_name   =item.odoo_journal_name,
                odoo_journal_type=item.odoo_journal_type,
                odoo_journal_code=item.odoo_journal_code,
                woocommerce_payment_method_id=item.woocommerce_payment_method_id,
                woocommerce_payment_method_name=item.woocommerce_payment_method_name,
                sync_status="synced" if item.last_synced_at else "never_synced",
                last_synced_at=item.last_synced_at,
                has_error=item.error,
                error_message=item.error_details if item.error else None
                ) for item in payment_jpurnals
        ],
        total_count= len(payment_jpurnals)
    )

@router.post("/payment-journals")
async def create_payment_journal_mapping(
    payment_journal: PaymentJournalCreate,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Create a mapping between a WooCommerce payment method and an Odoo journal.
    This is the main endpoint requested by the user.
    """
    try:
        # Get active instance
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        if not instance:
            raise HTTPException(
                status_code=404,
                detail="No active instance found"
            )
        
        # Check if mapping already exists for this WooCommerce payment method and instance
        sync_repo = PaymentJournalSyncRepository(db)
        existing_mapping = sync_repo.get_by_woocommerce_payment_method_id_and_instance(
            payment_journal.woocommerce_payment_method_id, instance.id)
        
        if existing_mapping:
            # Update existing mapping
            updated_mapping = sync_repo.update_sync_record(
                existing_mapping,
                woocommerce_payment_method_name=payment_journal.woocommerce_payment_method_name,
                odoo_journal_id=payment_journal.odoo_journal_id,
                odoo_journal_name=payment_journal.odoo_journal_name,
                odoo_journal_type=payment_journal.odoo_journal_type,
                odoo_journal_code=payment_journal.odoo_journal_code,
                message="Mapping updated via API"
            )
            
            return PaymentJournalSyncStatusResponse(
                odoo_id=updated_mapping.odoo_journal_id,
                odoo_name=updated_mapping.odoo_journal_name,
                odoo_journal_type=updated_mapping.odoo_journal_type,
                odoo_journal_code=updated_mapping.odoo_journal_code,
                woocommerce_payment_method_id=updated_mapping.woocommerce_payment_method_id,
                woocommerce_payment_method_name=updated_mapping.woocommerce_payment_method_name,
                sync_status="synced" if updated_mapping.last_synced_at else "never_synced",
                last_synced_at=updated_mapping.last_synced_at,
                has_error=updated_mapping.error,
                error_message=updated_mapping.error_details if updated_mapping.error else None
            )
        else:
            # Create new mapping
            new_mapping = sync_repo.create_sync_record(
                woocommerce_payment_method_id=payment_journal.woocommerce_payment_method_id,
                woocommerce_payment_method_name=payment_journal.woocommerce_payment_method_name,
                odoo_journal_id=payment_journal.odoo_journal_id,
                odoo_journal_name=payment_journal.odoo_journal_name,
                odoo_journal_type=payment_journal.odoo_journal_type,
                odoo_journal_code=payment_journal.odoo_journal_code,
                instance_id=instance.id,
                message="Mapping created via API"
            )
            
            return PaymentJournalSyncStatusResponse(
                id=new_mapping.id,
                odoo_journal_id=new_mapping.odoo_journal_id,
                odoo_journal_name=new_mapping.odoo_journal_name,
                odoo_journal_type=new_mapping.odoo_journal_type,
                odoo_journal_code=new_mapping.odoo_journal_code,
                woocommerce_payment_method_id=new_mapping.woocommerce_payment_method_id,
                woocommerce_payment_method_name=new_mapping.woocommerce_payment_method_name,
                sync_status="never_synced",  # Initially never synced
                last_synced_at=new_mapping.last_synced_at,
                has_error=new_mapping.error,
                error_message=new_mapping.error_details if new_mapping.error else None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating payment journal mapping: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error creating payment journal mapping: {str(e)}"
        )

@router.delete("/payment-journals/{journal_id}", 
               summary="Delete a payment journal mapping")
def delete_payment_journal_mapping(
    journal_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Delete a payment journal mapping by its record ID.
    """
    try:
        # Get instance configuration
        instance = crud_instance.get_active_instance(db, user_id=current_user.id)
        if not instance:
            raise HTTPException(
                status_code=404,
                detail="No active instance found"
            )
        
        # Find mapping by record ID and instance
        sync_repo = PaymentJournalSyncRepository(db)
        existing_mapping = db.query(PaymentJournalSync).filter(
            PaymentJournalSync.id == journal_id,
            PaymentJournalSync.instance_id == instance.id
        ).first()
        
        if not existing_mapping:
            raise HTTPException(
                status_code=404,
                detail="No payment journal mapping found"
            )
        
        # Delete the mapping
        sync_repo.delete_sync_record(existing_mapping)
        
        return {
            "status": "success",
            "message": f"Payment journal mapping deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting payment journal mapping: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting payment journal mapping: {str(e)}"
        )