"""
Category and Tag Management endpoints for Odoo-WooCommerce synchronization.
"""
from fastapi.responses import JSONResponse
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.crud.odoo import OdooClient
from app.repositories import CategorySyncRepository, TagSyncRepository
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.utils.instance_helpers import get_active_instance, get_active_instance_id, get_instance_configs
from app.tasks.sync_tasks import sync_category_to_woocommerce, sync_eco_category_to_woocommerce, sync_tag_to_woocommerce
from app.tasks.task_monitoring import create_task_response
from app.api.v1.endpoints.odoo import get_odoo_from_active_instance
from app.services.woocommerce import get_wc_api_from_instance_config
from celery import group
from pydantic import BaseModel
from datetime import datetime
from app.crud import instance as crud_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/category-tag-management",
                   tags=["Category & Tag Management"])


# ==================== Schemas ====================

class CategorySyncStatusResponse(BaseModel):
    """Category with sync status"""
    odoo_id: int
    name: str
    complete_name: Optional[str] = None  # Full hierarchical path
    parent_id: Optional[int] = None
    image_1920: Optional[str] = None
    website_description: Optional[str] = None
    sync_status: str  # never_synced, synced, error
    woocommerce_id: Optional[int] = None
    last_synced_at: Optional[datetime] = None
    has_error: bool = False
    error_message: Optional[str] = None


class TagSyncStatusResponse(BaseModel):
    """Tag with sync status"""
    odoo_id: int
    name: str
    sync_status: str  # never_synced, synced, error
    woocommerce_id: Optional[int] = None
    last_synced_at: Optional[datetime] = None
    has_error: bool = False
    error_message: Optional[str] = None


class CategoryListResponse(BaseModel):
    """Response for category list"""
    total_count: int
    categories: List[CategorySyncStatusResponse]
    filters_applied: dict


class TagListResponse(BaseModel):
    """Response for tag list"""
    total_count: int
    tags: List[TagSyncStatusResponse]
    filters_applied: dict


class BatchSyncRequest(BaseModel):
    """Request for batch sync"""
    ids: List[int]


class BatchSyncResponse(BaseModel):
    """Response for batch sync"""
    total: int
    queued: int
    task_ids: List[str]
    message: str


class SyncStatsResponse(BaseModel):
    """Sync statistics"""
    total: int
    synced: int
    never_synced: int
    errors: int


# ==================== Category Endpoints ====================

# @router.get("/categories", response_model=CategoryListResponse)
# async def list_odoo_categories_with_sync_status(
#     limit: int = Query(
#         50, le=200, description="Number of categories to return"),
#     offset: int = Query(0, ge=0, description="Offset for pagination"),
#     filter_status: Optional[str] = Query(
#         None,
#         description="Filter by sync status: never_synced, synced, error"
#     ),
#     search: Optional[str] = Query(None, description="Search by category name"),
#     db: Session = Depends(get_db),
#     odoo: OdooClient = Depends(get_odoo_from_active_instance),
#     current_user: Admin = Depends(get_current_user)
# ):
#     """
#     List Odoo categories with their WooCommerce sync status.
#     """
#     try:
#         # Authenticate with Odoo
#         uid = await odoo.odoo_authenticate()
#         if not uid:
#             raise HTTPException(
#                 status_code=400, detail="Failed to authenticate with Odoo")
#         # Build Odoo domain for filtering
#         domain = []
#         if search:
#             domain.append(["name", "ilike", search])

#         logger.info(
#             f"Fetching categories from Odoo: domain={domain}, limit={limit}")

#         # Fetch from Odoo
#         instance = crud_instance.get_active_instance(
#             db, user_id=current_user.id)
#         categ_model = "product.public.category" if not instance.category_from_product else "product.category"
#         fields = ["id", "name", "complete_name", "parent_id"] if instance.category_from_product else [
#             "id", "name", "parent_id"]
#         search_count = await odoo.search_count(
#             uid,
#             categ_model,
#             domain=[]
#         )
#         ctaegories_count = search_count["result"]
# Import additional required modules

# ==================== Common Util Functions ====================


def enrich_with_sync_status(items, sync_repo, instance_id):
    """Enrich items with sync status"""
    enriched_items = []
    for item in items:
        sync_record = sync_repo.get_sync_by_odoo_id(item["id"], instance_id)
        sync_status = (
            "never_synced" if not sync_record else
            "error" if sync_record.error else
            "synced"
        )
        enriched_items.append({
            "odoo_id": item["id"],
            "name": item.get("name", ""),
            "complete_name": item.get("complete_name", item.get("display_name", "")),
            "parent_id": item.get("parent_id", [None])[0] if item.get("parent_id") and isinstance(item.get("parent_id"), list) else None,
            "sync_status": sync_status,
            "woocommerce_id": getattr(sync_record, 'woocommerce_id', None),
            "last_synced_at": getattr(sync_record, 'last_synced_at', None),
            "has_error": getattr(sync_record, 'error', False),
            "error_message": getattr(sync_record, 'message', None) if getattr(sync_record, 'error', False) else None
        })
    return enriched_items

# Base function to list items with similar logic


async def list_entities_with_sync_status(entity_type, query_parameters, db, odoo, current_user, sync_repository_class):
    try:
        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")

        # Fetch from Odoo
        instance_id = get_active_instance(db, current_user)
        entity_model = "product.tag" if entity_type == "tag" else "product.public.category" if not instance_id.category_from_product else "product.category"
        odoo_response = await odoo.search_read(
            uid,
            entity_model,
            domain=query_parameters["domain"] if "domain" in query_parameters else [
            ],
            fields=query_parameters["fields"],
            limit=query_parameters.get("limit", 50),
            offset=query_parameters.get("offset", 0)
        )
        odoo_entities = odoo_response.get("result", [])

        # Enrich with sync status
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = sync_repository_class(db)
        enriched_entities = enrich_with_sync_status(
            odoo_entities, sync_repo, instance_id)

        # Filtering
        filtered_entities = [
            entity for entity in enriched_entities
            if query_parameters.get("filter_status") is None or entity["sync_status"] == query_parameters["filter_status"]
        ]

        # response_model = TagListResponse if entity_type == "tag" else CategoryListResponse

        response = CategoryListResponse(
            total_count=len(filtered_entities),
            categories=[CategorySyncStatusResponse(
                **e) for e in filtered_entities],
            filters_applied={
                "status": query_parameters.get("filter_status"),
                "search": query_parameters.get("search"),
                "limit": query_parameters.get("limit"),
                "offset": query_parameters.get("offset")
            }
        ) if entity_type == "category" else TagListResponse(
            total_count=len(filtered_entities),
            tags=[TagSyncStatusResponse(**e) for e in filtered_entities],
            filters_applied={
                "status": query_parameters.get("filter_status"),
                "search": query_parameters.get("search"),
                "limit": query_parameters.get("limit"),
                "offset": query_parameters.get("offset")
            }
        )
        return response

    except Exception as e:
        logger.error(
            f"Error fetching {entity_type}s with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching {entity_type}s: {str(e)}")

# Example usage for Category


@router.get("/categories", response_model=CategoryListResponse)
async def list_odoo_categories_with_sync_status(
    limit: int = Query(
        50, le=200, description="Number of categories to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None, description="Filter by sync status: never_synced, synced, error"),
    search: Optional[str] = Query(None, description="Search by category name"),
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    instance_id = get_active_instance(db, current_user)
    query_parameters = {
        "domain": [["name", "ilike", search]] if search else [],
        "fields": ["id", "name", "complete_name", "parent_id"] if instance_id.category_from_product
        else ["id", "name", "parent_id", "display_name", "image_1920", "website_description"],
        "limit": limit,
        "offset": offset,
        "filter_status": filter_status,
        "search": search
    }
    return await list_entities_with_sync_status("category", query_parameters, db, odoo, current_user, CategorySyncRepository)

# You would similarly define for tags with necessary adjustments in fields, domain and repository class use
    #         uid,
    #         categ_model,
    #         domain=domain if domain else [],
    #         fields=fields,
    #         limit=limit,
    #         offset=offset
    #     )

    #     odoo_categories = odoo_response.get("result", [])
    #     logger.info(f"Fetched {len(odoo_categories)} categories from Odoo")

    #     # Get instance ID
    #     instance_id = get_active_instance_id(db, current_user)

    #     # Enrich with sync status
    #     sync_repo = CategorySyncRepository(db)
    #     enriched_categories = []

    #     for category in odoo_categories:
    #         sync_record = sync_repo.get_sync_by_odoo_id(
    #             category["id"], instance_id)

    #         # Calculate sync status
    #         if not sync_record:
    #             sync_status = "never_synced"
    #         elif sync_record.error:
    #             sync_status = "error"
    #         else:
    #             sync_status = "synced"

    #         # Apply filter
    #         if filter_status and sync_status != filter_status:
    #             continue

    #         enriched_categories.append({
    #             "odoo_id": category["id"],
    #             "name": category.get("name", ""),
    #             "complete_name": category.get("complete_name", category.get("name", "")),
    #             "parent_id": category.get("parent_id")[0] if category.get("parent_id") and isinstance(category.get("parent_id"), list) else None,
    #             "sync_status": sync_status,
    #             "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
    #             "last_synced_at": sync_record.last_synced_at if sync_record else None,
    #             "has_error": sync_record.error if sync_record else False,
    #             "error_message": sync_record.message if sync_record and sync_record.error else None
    #         })

    #     logger.info(
    #         f"Returning {len(enriched_categories)} categories after filtering")

    #     return CategoryListResponse(
    #         total_count=ctaegories_count,
    #         categories=[CategorySyncStatusResponse(
    #             **c) for c in enriched_categories],
    #         filters_applied={
    #             "status": filter_status,
    #             "search": search,
    #             "limit": limit,
    #             "offset": offset
    #         }
    #     )

    # except Exception as e:
    #     logger.error(
    #         f"Error fetching categories with sync status: {e}", exc_info=True)
    #     raise HTTPException(
    #         status_code=500, detail=f"Error fetching categories: {str(e)}")


@router.post("/categories/batch-sync", response_model=BatchSyncResponse)
async def batch_sync_categories(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue multiple categories for synchronization to WooCommerce.
    """
    try:
        # Get instance configurations
        odoo_config, wc_config, instance_id = get_instance_configs(
            db, current_user)

        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")
        # Fetch category data from Odoo
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        categ_model = "product.public.category" if not instance.category_from_product else "product.category"
        odoo_response = await odoo.search_read(
            uid,
            categ_model,
            # domain=[],
            # domain=[["id", "in", request.ids]],
            fields=["id", "name", "complete_name", "parent_id"]
            if instance.category_from_product else ["id", "name",
                                                    "parent_id",
                                                    "display_name",
                                                    "image_1920", "website_description"
                                                    ]
        )
        all_categories = odoo_response.get("result", [])
        categories_filtered = [
            cat for cat in all_categories if cat["id"] in request.ids]
        categories = categories_filtered

        if not categories:
            raise HTTPException(
                status_code=404,
                detail=f"No categories found with IDs: {request.ids}"
            )

        logger.info(f"Starting batch sync for {len(categories)} categories")
        logger.info(f"Instance ID: {instance_id}")
        logger.info(
            f"Categories to sync: {[cat.get('id') for cat in categories]}")

        # Queue tasks individually with explicit queue
        task_ids = []
        for cat in categories:
            try:
                logger.info(
                    f"Queuing category {cat.get('id')}: {cat.get('name')}")
                task = None
                if instance.category_from_product:
                    task = sync_category_to_woocommerce.apply_async(
                        args=[cat, all_categories, instance_id],
                        kwargs={
                            "odoo_config": odoo_config,
                            "wc_config": wc_config
                        },
                        queue="sync_queue"
                    )
                else:
                    task = sync_eco_category_to_woocommerce.apply_async(
                        args=[cat, all_categories, instance_id],
                        kwargs={
                            "odoo_config": odoo_config,
                            "wc_config": wc_config
                        },
                        queue="sync_queue"
                    )
                task_ids.append(str(task.id))
                logger.info(
                    f"Category {cat.get('id')} queued with task_id: {task.id}")
            except Exception as e:
                logger.error(
                    f"Error queuing category {cat.get('id')}: {e}", exc_info=True)

        logger.info(f"Successfully queued {len(task_ids)} categories for sync")

        return BatchSyncResponse(
            total=len(request.ids),
            queued=len(task_ids),
            task_ids=task_ids,
            message=f"Successfully queued {len(task_ids)} categories for synchronization"
        )

    except Exception as e:
        logger.error(f"Error batch syncing categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error syncing categories: {str(e)}")


@router.get("/categories/statistics", response_model=SyncStatsResponse)
async def get_category_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get category sync statistics.
    """
    try:
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = CategorySyncRepository(db)
        stats = sync_repo.get_sync_stats(instance_id)

        return SyncStatsResponse(
            total=stats["total"],
            synced=stats["created"] + stats["updated"],
            never_synced=0,  # Would need to query Odoo for total categories
            errors=stats["errors"]
        )

    except Exception as e:
        logger.error(f"Error getting category statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Category ecommerce Endpoints ====================

@router.get("/ecommerce/categories", response_model=CategoryListResponse)
async def eco_list_odoo_categories_with_sync_status(
    limit: int = Query(
        50, le=200, description="Number of categories to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None,
        description="Filter by sync status: never_synced, synced, error"
    ),
    search: Optional[str] = Query(None, description="Search by category name"),
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    List Odoo categories with their WooCommerce sync status.
    """
    try:
        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")
        # Build Odoo domain for filtering
        domain = []
        if search:
            domain.append(["name", "ilike", search])

        logger.info(
            f"Fetching categories from Odoo: domain={domain}, limit={limit}")

        # Fetch from Odoo

        search_count = await odoo.search_count(
            uid,
            "product.public.category",
            domain=[]
        )
        ctaegories_count = search_count["result"]
        odoo_response = await odoo.search_read(
            uid,
            "product.public.category",
            domain=domain if domain else [],
            fields=["id", "name", "complete_name", "parent_id"],
            limit=limit,
            offset=offset
        )

        odoo_categories = odoo_response.get("result", [])
        logger.info(f"Fetched {len(odoo_categories)} categories from Odoo")

        # Get instance ID
        instance_id = get_active_instance_id(db, current_user)

        # Enrich with sync status
        sync_repo = CategorySyncRepository(db)
        enriched_categories = []

        for category in odoo_categories:
            sync_record = sync_repo.get_sync_by_odoo_id(
                category["id"], instance_id)

            # Calculate sync status
            if not sync_record:
                sync_status = "never_synced"
            elif sync_record.error:
                sync_status = "error"
            else:
                sync_status = "synced"

            # Apply filter
            if filter_status and sync_status != filter_status:
                continue

            enriched_categories.append({
                "odoo_id": category["id"],
                "name": category.get("name", ""),
                "complete_name": category.get("complete_name", category.get("name", "")),
                "image_1920": category.get("image_1920", ""),
                "website_description": category.get("website_description", ""),
                "parent_id": category.get("parent_id")[0] if category.get("parent_id") and isinstance(category.get("parent_id"), list) else None,
                "sync_status": sync_status,
                "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
                "last_synced_at": sync_record.last_synced_at if sync_record else None,
                "has_error": sync_record.error if sync_record else False,
                "error_message": sync_record.message if sync_record and sync_record.error else None
            })

        logger.info(
            f"Returning {len(enriched_categories)} categories after filtering")

        return CategoryListResponse(
            total_count=ctaegories_count,
            categories=[CategorySyncStatusResponse(
                **c) for c in enriched_categories],
            filters_applied={
                "status": filter_status,
                "search": search,
                "limit": limit,
                "offset": offset
            }
        )

    except Exception as e:
        logger.error(
            f"Error fetching categories with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching categories: {str(e)}")


@router.post("/ecommerce/categories/batch-sync", response_model=BatchSyncResponse)
async def eco_batch_sync_categories(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue multiple categories for synchronization to WooCommerce.
    """
    try:
        # Get instance configurations
        odoo_config, wc_config, instance_id = get_instance_configs(
            db, current_user)

        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")
        # Fetch category data from Odoo
        odoo_response = await odoo.search_read(
            uid,
            "product.public.category",
            # domain=[],
            # domain=[["id", "in", request.ids]],
            fields=["id", "name", "complete_name", "parent_id",
                    "image_1920", "website_description"]
        )
        all_categories = odoo_response.get("result", [])
        categories_filtered = [
            cat for cat in all_categories if cat["id"] in request.ids]
        categories = categories_filtered

        if not categories:
            raise HTTPException(
                status_code=404,
                detail=f"No categories found with IDs: {request.ids}"
            )

        logger.info(f"Starting batch sync for {len(categories)} categories")
        logger.info(f"Instance ID: {instance_id}")
        logger.info(
            f"Categories to sync: {[cat.get('id') for cat in categories]}")

        # Queue tasks individually with explicit queue
        task_ids = []
        for cat in categories:
            try:
                logger.info(
                    f"Queuing category {cat.get('id')}: {cat.get('name')}")
                task = sync_eco_category_to_woocommerce.apply_async(
                    args=[cat, all_categories, instance_id],
                    kwargs={
                        "odoo_config": odoo_config,
                        "wc_config": wc_config
                    },
                    queue="sync_queue"
                )
                task_ids.append(str(task.id))
                logger.info(
                    f"Category {cat.get('id')} queued with task_id: {task.id}")
            except Exception as e:
                logger.error(
                    f"Error queuing category {cat.get('id')}: {e}", exc_info=True)

        logger.info(f"Successfully queued {len(task_ids)} categories for sync")

        return BatchSyncResponse(
            total=len(request.ids),
            queued=len(task_ids),
            task_ids=task_ids,
            message=f"Successfully queued {len(task_ids)} categories for synchronization"
        )

    except Exception as e:
        logger.error(f"Error batch syncing categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error syncing categories: {str(e)}")


@router.get("/ecommerce/categories/statistics", response_model=SyncStatsResponse)
async def get_category_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get category sync statistics.
    """
    try:
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = CategorySyncRepository(db)
        stats = sync_repo.get_sync_stats(instance_id)

        return SyncStatsResponse(
            total=stats["total"],
            synced=stats["created"] + stats["updated"],
            never_synced=0,  # Would need to query Odoo for total categories
            errors=stats["errors"]
        )

    except Exception as e:
        logger.error(f"Error getting category statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Tag Endpoints ====================

@router.get("/tags", response_model=TagListResponse)
async def list_odoo_tags_with_sync_status(
    limit: int = Query(50, le=200, description="Number of tags to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None,
        description="Filter by sync status: never_synced, synced, error"
    ),
    search: Optional[str] = Query(None, description="Search by tag name"),
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    List Odoo tags with their WooCommerce sync status.
    """
    try:
        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")
        # Build Odoo domain for filtering
        domain = []
        if search:
            domain.append(["name", "ilike", search])

        logger.info(f"Fetching tags from Odoo: domain={domain}, limit={limit}")

        # Fetch from Odoo
        odoo_response = await odoo.search_read(
            uid,
            "product.tag",
            domain=domain if domain else [],
            fields=["id", "name"],
            limit=limit,
            offset=offset
        )

        odoo_tags = odoo_response.get("result", [])
        logger.info(f"Fetched {len(odoo_tags)} tags from Odoo")

        # Get instance ID
        instance_id = get_active_instance_id(db, current_user)

        # Enrich with sync status
        sync_repo = TagSyncRepository(db)
        enriched_tags = []

        for tag in odoo_tags:
            sync_record = sync_repo.get_sync_by_odoo_id(
                tag["id"], instance_id)

            # Calculate sync status
            if not sync_record:
                sync_status = "never_synced"
            elif sync_record.error:
                sync_status = "error"
            else:
                sync_status = "synced"

            # Apply filter
            if filter_status and sync_status != filter_status:
                continue

            enriched_tags.append({
                "odoo_id": tag["id"],
                "name": tag.get("name", ""),
                "sync_status": sync_status,
                "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
                "last_synced_at": sync_record.last_synced_at if sync_record else None,
                "has_error": sync_record.error if sync_record else False,
                "error_message": sync_record.message if sync_record and sync_record.error else None
            })

        logger.info(f"Returning {len(enriched_tags)} tags after filtering")

        return TagListResponse(
            total_count=len(enriched_tags),
            tags=[TagSyncStatusResponse(**t) for t in enriched_tags],
            filters_applied={
                "status": filter_status,
                "search": search,
                "limit": limit,
                "offset": offset
            }
        )

    except Exception as e:
        logger.error(
            f"Error fetching tags with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching tags: {str(e)}")


@router.post("/tags/batch-sync", response_model=BatchSyncResponse)
async def batch_sync_tags(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_from_active_instance),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue multiple tags for synchronization to WooCommerce.
    """
    try:
        # Get instance configurations
        odoo_config, wc_config, instance_id = get_instance_configs(
            db, current_user)

        # Authenticate with Odoo
        uid = await odoo.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=400, detail="Failed to authenticate with Odoo")
        # Fetch tag data from Odoo
        odoo_response = await odoo.search_read(
            uid,
            "product.tag",
            domain=[["id", "in", request.ids]],
            fields=["id", "name"]
        )

        tags = odoo_response.get("result", [])

        if not tags:
            raise HTTPException(
                status_code=404,
                detail=f"No tags found with IDs: {request.ids}"
            )

        logger.info(f"Starting batch sync for {len(tags)} tags")
        logger.info(f"Instance ID: {instance_id}")
        logger.info(f"Tags to sync: {[tag.get('id') for tag in tags]}")

        # Queue tasks individually with explicit queue
        task_ids = []
        for tag in tags:
            try:
                logger.info(f"Queuing tag {tag.get('id')}: {tag.get('name')}")
                task = sync_tag_to_woocommerce.apply_async(
                    args=[tag, instance_id],
                    kwargs={
                        "odoo_config": odoo_config,
                        "wc_config": wc_config
                    },
                    queue="sync_queue"
                )
                task_ids.append(str(task.id))
                logger.info(
                    f"Tag {tag.get('id')} queued with task_id: {task.id}")
            except Exception as e:
                logger.error(
                    f"Error queuing tag {tag.get('id')}: {e}", exc_info=True)

        logger.info(f"Successfully queued {len(task_ids)} tags for sync")

        return BatchSyncResponse(
            total=len(request.ids),
            queued=len(task_ids),
            task_ids=task_ids,
            message=f"Successfully queued {len(task_ids)} tags for synchronization"
        )

    except Exception as e:
        logger.error(f"Error batch syncing tags: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error syncing tags: {str(e)}")


@router.get("/tags/statistics", response_model=SyncStatsResponse)
async def get_tag_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get tag sync statistics.
    """
    try:
        instance_id = get_active_instance_id(db, current_user)
        sync_repo = CategorySyncRepository(db)
        stats = sync_repo.get_sync_stats(instance_id)

        return SyncStatsResponse(
            total=stats["total"],
            synced=stats["created"] + stats["updated"],
            never_synced=0,  # Would need to query Odoo for total tags
            errors=stats["errors"]
        )

    except Exception as e:
        logger.error(f"Error getting tag statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
