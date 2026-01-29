"""WooCommerce category management."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from woocommerce import API
import redis
from redis.lock import Lock as RedisLock

from app.models.product_models import OdooCategory, CategorySyncResult, WooCommerceCategoryCreate
from app.models.admin import CategorySync
from app.services.woocommerce.client import wc_request
from app.repositories.category_sync_repository import CategorySyncRepository
from app.core.config import settings

__logger__ = logging.getLogger(__name__)

# Initialize Redis client for distributed locks
try:
    redis_client = redis.Redis.from_url(
        settings.celery_broker_url, decode_responses=True)
    __logger__.info("Redis client initialized for category locks")
except Exception as e:
    __logger__.warning(
        f"Failed to initialize Redis client: {e}. Category locks will be disabled.")
    redis_client = None


def build_category_chain(category_id, categories_by_id):
    chain = []
    current = categories_by_id.get(category_id)

    while current:
        chain.append(current)
        current = categories_by_id.get(current["parent_id"])

    return list(reversed(chain))


def category_for_export(
    category_data: dict,
    db: Session = None,
    wcapi: API = None,
    instance_id: Optional[int] = None
) -> Optional[List[Dict[str, int]]]:
    """
    Manage creation and export of hierarchical categories to WooCommerce.
    Similar to ks_manage_category_to_export from Odoo module.

    Args:
        category_data: Dictionary containing category details
        db: Database session for tracking
        wcapi: WooCommerce API client (uses settings if not provided)
        instance_id: WooCommerce instance ID (for multi-tenancy)

    Returns:
        List with WooCommerce category ID [{"id": 123}]
    """

    # DISTRIBUTED LOCK: Prevent race conditions with Redis
    lock_key = f"category_sync:{category_data.get('id')}:{instance_id}"
    lock_timeout = 300  # 5 minutes max lock time
    lock = None

    try:
        # Acquire distributed lock if Redis is available
        if redis_client:
            lock = RedisLock(redis_client, lock_key,
                             timeout=lock_timeout, blocking_timeout=10)
            acquired = lock.acquire(blocking=True)
            if not acquired:
                __logger__.warning(
                    f"Could not acquire lock for category {category_data.get('id')}, skipping sync"
                )
                return None
            __logger__.info(
                f"Acquired lock for category {category_data.get('id')}")

        repo = CategorySyncRepository(db)
        existing_sync = db.query(CategorySync).filter(
            CategorySync.odoo_id == category_data.get("id"),
            CategorySync.instance_id == instance_id
        ).first()
        woocommerce_id = existing_sync.woocommerce_id if existing_sync else None
        slug = category_data["name"].replace(" ", "-").lower().strip()
        slug = slug + '-' + str(category_data.get("id", "")) + '-' + str(instance_id)
        parent = db.query(CategorySync).filter(
            CategorySync.odoo_id == category_data.get("parent_id"),
            CategorySync.instance_id == instance_id
        ).first() if category_data.get("parent_id") else None
        __logger__.info(
            f"Preparing to export category {category_data['name']} "
            f"(Odoo ID: {category_data.get('id')}) to WooCommerce"
        )
        existing_in_woo = None
        if not woocommerce_id:
            __logger__.info(
                f"Searching category {category_data['name']} in WooCommerce")
            # Search category in WooCommerce
            search_params = {"slug": slug, "per_page": 1}
            response = wc_request(
                "GET", "products/categories", params=search_params, wcapi=wcapi)
            if response:
                existing_in_woo = response[0]
                wc_product_id = response[0]["id"]

                # CONFLICT VALIDATION BEFORE assigning: Check if found WC category already mapped to different Odoo category
                existing_mapping = db.query(CategorySync).filter(
                    CategorySync.woocommerce_id == wc_product_id,
                    CategorySync.instance_id == instance_id,
                    CategorySync.odoo_id != category_data.get("id")
                ).first()

                if existing_mapping:
                    __logger__.error(
                        f"CONFLICT: WooCommerce category ID {wc_product_id} (found by slug) already mapped to "
                        f"Odoo category {existing_mapping.odoo_id}. Cannot map to {category_data.get('id')}. "
                        f"Creating new category instead."
                    )
                    # Don't use this WC category, will create new one
                    existing_in_woo = None
                else:
                    # No conflict, safe to use this WC category
                    __logger__.info(
                        f"Category {category_data['name']} found in WooCommerce (ID: {wc_product_id})")
                    woocommerce_id = wc_product_id

        # CONFLICT VALIDATION for existing sync record
        if woocommerce_id and existing_sync:
            # Verify this WC ID isn't mapped to a different Odoo category
            existing_mapping = db.query(CategorySync).filter(
                CategorySync.woocommerce_id == woocommerce_id,
                CategorySync.instance_id == instance_id,
                CategorySync.odoo_id != category_data.get("id")
            ).first()

            if existing_mapping:
                __logger__.error(
                    f"CONFLICT: WooCommerce category ID {woocommerce_id} already mapped to "
                    f"Odoo category {existing_mapping.odoo_id}. Cannot map to {category_data.get('id')}."
                )
                return None

        if woocommerce_id:
            __logger__.info(
                f"Category {category_data['name']} exists in WooCommerce (ID: {woocommerce_id})")
            # Update existing category
            update_data = {"name": category_data["name"],"slug": slug}
            if parent:
                update_data["parent"] = parent.woocommerce_id

            # Get current WC category to compare
            if not existing_in_woo:
                try:
                    existing_in_woo = wc_request(
                        "GET",
                        f"products/categories/{woocommerce_id}",
                        wcapi=wcapi
                    )
                except Exception as e:
                    __logger__.warning(
                        f"Could not fetch WC category {woocommerce_id}: {e}")

            if existing_in_woo and category_data["name"] != existing_in_woo.get("name"):
                __logger__.info(
                    f"Updating category {category_data['name']} in WooCommerce (ID: {woocommerce_id})")
                response = wc_request(
                    "PUT",
                    f"products/categories/{woocommerce_id}",
                    params=update_data,
                    wcapi=wcapi
                )
        else:
            # Create new category
            __logger__.info(
                f"Category {category_data['name']} not found in WooCommerce, creating new")
            category_data_wc = {
                "name": category_data["name"],
                "slug": slug
            }
            if parent:
                category_data_wc["parent"] = parent.woocommerce_id
            __logger__.info(
                f"Creating category {category_data['name']} in WooCommerce")
            response = wc_request(
                "POST", "products/categories", params=category_data_wc, wcapi=wcapi
            )
            wc_product_id = response["id"]

            # CONFLICT VALIDATION AFTER CREATE: Verify newly created ID doesn't conflict
            existing_mapping = db.query(CategorySync).filter(
                CategorySync.woocommerce_id == wc_product_id,
                CategorySync.instance_id == instance_id,
                CategorySync.odoo_id != category_data.get("id")
            ).first()

            if existing_mapping:
                __logger__.error(
                    f"CONFLICT AFTER CREATE: WooCommerce category ID {wc_product_id} already mapped to "
                    f"Odoo category {existing_mapping.odoo_id}. New category created but cannot sync."
                )
                return None

            woocommerce_id = wc_product_id

        # RE-CHECK existing_sync JUST BEFORE creating/updating to prevent race condition
        # Another worker may have created a record between initial check and now
        existing_sync = db.query(CategorySync).filter(
            CategorySync.odoo_id == category_data.get("id"),
            CategorySync.instance_id == instance_id
        ).first()

        if existing_sync:
            # Update existing record
            updated_sync = repo.update_sync_record(
                existing_sync,
                woocommerce_id=woocommerce_id,
                created=True,
                last_synced_at=datetime.utcnow(),
                message=f"Category updated: {category_data['name']}"
            )
            __logger__.info(
                f"Updated existing sync record for category {category_data.get('id')} -> WC {woocommerce_id}"
            )
        else:
            # Create new record - but use try/except to handle race condition
            try:
                new_sync = repo.create_sync_record(
                    odoo_id=category_data.get("id"),
                    woocommerce_id=woocommerce_id,
                    odoo_name=category_data["name"],
                    instance_id=instance_id,
                    created=True,
                    last_synced_at=datetime.utcnow(),
                    message=f"Category created: {category_data['name']}"
                )
                __logger__.info(
                    f"Created new sync record for category {category_data.get('id')} -> WC {woocommerce_id}"
                )
            except IntegrityError as ie:
                # Another worker created the record just now - fetch it and update
                db.rollback()
                __logger__.warning(
                    f"Race condition detected: sync record already exists for category {category_data.get('id')}, fetching and updating"
                )
                existing_sync = db.query(CategorySync).filter(
                    CategorySync.odoo_id == category_data.get("id"),
                    CategorySync.instance_id == instance_id
                ).first()
                if existing_sync:
                    updated_sync = repo.update_sync_record(
                        existing_sync,
                        woocommerce_id=woocommerce_id,
                        created=True,
                        last_synced_at=datetime.utcnow(),
                        message=f"Category updated after race condition: {category_data['name']}"
                    )
                else:
                    __logger__.error(
                        f"Could not find sync record after IntegrityError for category {category_data.get('id')}"
                    )
                    raise

        return [{"id": woocommerce_id}]
    except IntegrityError as e:
        # Database constraint violation (duplicate WooCommerce ID)
        if db:
            db.rollback()
        __logger__.error(
            f"IntegrityError syncing category {category_data['name']}: {e}"
        )
        return None
    except Exception as e:
        __logger__.error(
            f"Error handling category {category_data['name']}: {e}")
        return None
    finally:
        # ALWAYS release the lock
        if lock:
            try:
                lock.release()
                __logger__.info(
                    f"Released lock for category {category_data.get('id')}")
            except Exception as e:
                __logger__.warning(f"Error releasing category lock: {e}")


def manage_category_for_export(
    category_full_path: str,
    db: Session = None,
    odoo_category_id: int = None,
    wcapi: API = None,
    instance_id: Optional[int] = None
) -> Optional[List[Dict[str, int]]]:
    """
    Manage creation and export of hierarchical categories to WooCommerce.
    Similar to ks_manage_category_to_export from Odoo module.

    Args:
        category_full_path: Full category path (e.g., "Electronics/Computers/Laptops")
        db: Database session for tracking
        odoo_category_id: Category ID in Odoo for tracking
        wcapi: WooCommerce API client (uses settings if not provided)
        instance_id: WooCommerce instance ID (for multi-tenancy)

    Returns:
        List with WooCommerce category ID [{"id": 123}]
    """
    if not category_full_path:
        __logger__.warning("category_full_path is empty")
        return None

    __logger__.info(f"Processing category: {category_full_path}")

    try:
        # First search in CategorySync if already synced
        existing_sync = None
        if db and odoo_category_id and instance_id:
            existing_sync = db.query(CategorySync).filter(
                CategorySync.odoo_id == odoo_category_id,
                CategorySync.instance_id == instance_id
            ).first()

            if existing_sync:
                __logger__.info(
                    f"Category already synced: Odoo {odoo_category_id} -> "
                    f"WC {existing_sync.woocommerce_id}"
                )

                # Verify category still exists in WooCommerce
                try:
                    wc_category = wc_request(
                        "GET",
                        f"products/categories/{existing_sync.woocommerce_id}",
                        wcapi=wcapi
                    )
                    if wc_category:
                        __logger__.info(
                            f"Category found in WooCommerce: {wc_category['name']} "
                            f"(ID: {wc_category['id']})"
                        )

                        # Update category if name changed
                        category_name = category_full_path.split(
                            "/")[-1].strip()
                        if wc_category.get("name") != category_name:
                            __logger__.info(
                                f"Updating category name: {wc_category.get('name')} -> "
                                f"{category_name}"
                            )
                            slug = category_name.replace(
                                " ", "-").lower() + str(odoo_category_id)
                            update_data = {"name": category_name, "slug": slug}
                            wc_request(
                                "PUT",
                                f"products/categories/{existing_sync.woocommerce_id}",
                                params=update_data,
                                wcapi=wcapi
                            )

                            # Update sync record
                            existing_sync.odoo_name = category_name
                            existing_sync.woocommerce_id = wc_category['id']
                            existing_sync.updated = True
                            existing_sync.message = f"Category updated: {category_name}"
                            existing_sync.last_synced_at = datetime.utcnow()
                            db.commit()
                            db.refresh(existing_sync)

                        return [{"id": existing_sync.woocommerce_id}]
                except Exception as e:
                    __logger__.warning(
                        f"WC category {existing_sync.woocommerce_id} not found, "
                        f"will create new: {e}"
                    )
                    # If doesn't exist in WooCommerce, continue with creation

        __logger__.warning("Could not get wc_category_id")
        return []

    except Exception as e:
        __logger__.error(f"Error handling category {category_full_path}: {e}")
        return None


async def find_woocommerce_category_by_name(name: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """Search for a category in WooCommerce by exact name."""
    try:
        categories = wc_request(
            "GET", "products/categories",
            params={"search": name, "per_page": 100},
            wcapi=wcapi
        )
        # Search for exact match
        for cat in categories:
            if cat.get("name", "").lower() == name.lower():
                return cat
        return None
    except Exception as e:
        __logger__.error(f"Error searching category by name {name}: {e}")
        return None


async def find_category_by_slug(slug: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """Search for a category in WooCommerce by slug."""
    try:
        categories = wc_request(
            "GET", f"products/categories?slug={slug}", wcapi=wcapi
        )
        # Search for exact match
        for cat in categories:
            if cat.get("slug", "") == slug:
                return cat
        return None
    except Exception as e:
        __logger__.error(f"Error searching category by slug {slug}: {e}")
        return None


async def create_or_update_woocommerce_category(
    odoo_category: OdooCategory,
    wc_category_data: WooCommerceCategoryCreate,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    categories_map: Dict[int, int] = None,
    wcapi: API = None
) -> CategorySyncResult:
    """Create or update a category in WooCommerce."""
    from fastapi import HTTPException

    result = CategorySyncResult(
        odoo_id=odoo_category.id,
        odoo_name=odoo_category.name,
        success=False,
        action="skipped",
        message="Not processed"
    )

    try:
        # Search for existing category by name
        existing_category = await find_woocommerce_category_by_name(
            odoo_category.name, wcapi=wcapi
        )

        # Convert Pydantic model to dict
        category_data = wc_category_data.dict(exclude_none=True)

        # If has parent category, search its ID in WooCommerce
        if odoo_category.parent_id and categories_map:
            wc_parent_id = categories_map.get(odoo_category.parent_id)
            if wc_parent_id:
                category_data["parent"] = wc_parent_id
            else:
                __logger__.warning(
                    f"Parent category {odoo_category.parent_id} not found in map"
                )

        if existing_category:
            # Category exists
            result.woocommerce_id = existing_category["id"]

            if update_existing:
                # Update existing category
                updated_category = wc_request(
                    "PUT",
                    f"products/categories/{existing_category['id']}",
                    params=category_data,
                    wcapi=wcapi
                )
                result.success = True
                result.action = "updated"
                result.message = f"Category updated: {updated_category['name']}"
                result.woocommerce_id = updated_category["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Category exists, update disabled"
        else:
            # Category doesn't exist
            if create_if_not_exists:
                # Create new category
                new_category = wc_request(
                    "POST", "products/categories", params=category_data, wcapi=wcapi
                )
                result.success = True
                result.action = "created"
                result.message = f"Category created: {new_category['name']}"
                result.woocommerce_id = new_category["id"]
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Category doesn't exist, creation disabled"

    except HTTPException as e:
        result.success = False
        result.action = "error"
        result.message = f"HTTP Error: {e.detail}"
        result.error_details = str(e)
    except Exception as e:
        result.success = False
        result.action = "error"
        result.message = f"Unexpected error: {str(e)}"
        result.error_details = str(e)
        __logger__.error(f"Error syncing category {odoo_category.name}: {e}")

    return result
