"""WooCommerce product management."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from woocommerce import API
import redis
from redis.lock import Lock as RedisLock

from app.models.product_models import OdooProduct, ProductSyncResult, WooCommerceProductCreate
from app.crud.admin import get_product_sync_by_odoo_id
from app.repositories import ProductSyncRepository
from app.services.woocommerce.client import wc_request
from app.core.config import settings

__logger__ = logging.getLogger(__name__)

# Initialize Redis client for distributed locks
try:
    redis_client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
    __logger__.info("Redis client initialized for distributed locks")
except Exception as e:
    __logger__.warning(f"Failed to initialize Redis client: {e}. Locks will be disabled.")
    redis_client = None


def find_woocommerce_product_by_sku(sku: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a product in WooCommerce by SKU.

    Args:
        sku: Product SKU to search
        wcapi: WooCommerce API client

    Returns:
        Product dict if found, None otherwise
    """
    if not sku:
        return None

    try:
        products = wc_request("GET", "products",
                              params={"sku": sku, "per_page": 1}, wcapi=wcapi)
        if products and len(products) > 0:
            # CRITICAL: Validate exact SKU match
            # WooCommerce search can return fuzzy results
            __logger__.info(f"Products found for SKU {sku}: {len(products)}")
            found_product = products[0]
            if found_product:
                if found_product.get("sku") == sku:
                    __logger__.info(f"Exact SKU match found: {sku}")
                    return found_product
            else:
                __logger__.warning(
                    f"SKU mismatch: searched '{sku}', got '{found_product.get('sku')}'. "
                    f"Ignoring fuzzy result."
                )
                return None
        return None
    except Exception as e:
        __logger__.info(f"Error searching product by SKU {sku}: {e}")
        return None


def find_woocommerce_product_by_slug(slug: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a product in WooCommerce by SKU.

    Args:
        sku: Product SKU to search
        wcapi: WooCommerce API client

    Returns:
        Product dict if found, None otherwise
    """
    if not slug:
        return None

    try:
        products = wc_request("GET", "products",
                              params={"slug": slug, "per_page": 1}, wcapi=wcapi)
        return products[0] if products else None
    except Exception as e:
        __logger__.error(f"Error searching product by slug {slug}: {e}")
        return None


def find_woocommerce_product_by_id(id: int, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a product in WooCommerce by ID.

    Args:
        id: Product ID
        wcapi: WooCommerce API client

    Returns:
        Product dict if found, None otherwise
    """
    if not id:
        return None

    try:
        products = wc_request("GET", f"products/{id}", wcapi=wcapi)
        return products if products else None
    except Exception as e:
        __logger__.error(f"Error searching product by ID {id}: {e}")
        return None


def create_or_update_woocommerce_product(
    odoo_product: OdooProduct,
    wc_product_data: WooCommerceProductCreate,
    instance_id: int,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    db: Session = None,
    wcapi: API = None
) -> ProductSyncResult:
    """
    Create or update a product in WooCommerce.

    Args:
        odoo_product: Odoo product object
        wc_product_data: WooCommerce product data
        instance_id: WooCommerce instance ID
        create_if_not_exists: Create if product doesn't exist
        update_existing: Update if product exists
        db: Database session
        wcapi: WooCommerce API client

    Returns:
        ProductSyncResult with sync operation details
    """
    
    __logger__.info(f"CREDENTIALS WC API: {wcapi.url}, {wcapi.consumer_key}, {wcapi.consumer_secret}")
    result = ProductSyncResult(
        odoo_id=odoo_product.id,
        odoo_sku=odoo_product.default_code,
        success=False,
        action="skipped",
        message="Not processed"
    )

    # DISTRIBUTED LOCK: Prevent race conditions with Redis
    lock_key = f"product_sync:{odoo_product.id}:{instance_id}"
    lock_timeout = 300  # 5 minutes max lock time
    lock = None
    
    try:
        # Acquire distributed lock if Redis is available
        if redis_client:
            lock = RedisLock(redis_client, lock_key, timeout=lock_timeout, blocking_timeout=10)
            acquired = lock.acquire(blocking=True)
            if not acquired:
                __logger__.warning(
                    f"Could not acquire lock for product {odoo_product.id}, skipping sync"
                )
                result.success = False
                result.action = "skipped"
                result.message = "Another worker is syncing this product"
                return result
            __logger__.info(f"Acquired lock for product {odoo_product.id}")
        
        # First search in sync table (faster)
        sync_repo = ProductSyncRepository(db) if db else None
        sync_product = get_product_sync_by_odoo_id(db, odoo_product.id, instance_id) if db else None
        wc_product_id = None
        __logger__.info(
            f"Syncing Odoo for {odoo_product.id}: {sync_product})"
        )
        if sync_product:
            # Already synced, use ID directly
            __logger__.info(
                f"Product searching. WooCommerce ID: {sync_product.woocommerce_id}"
            )
            existing_product = find_woocommerce_product_by_id(
                sync_product.woocommerce_id, wcapi=wcapi
            )
            if existing_product:
                __logger__.info(
                    f"Found existing WooCommerce product by ID: {existing_product['name']}"
                )
                wc_product_id = sync_product.woocommerce_id
        elif odoo_product.default_code:
            # Not in sync table, search in WooCommerce by SKU
            __logger__.info(
                f"Product. Searching by SKU: {odoo_product.default_code}"
            )
            existing_product = find_woocommerce_product_by_sku(
                odoo_product.default_code, wcapi=wcapi
            )
            __logger__.info(f"EXISTING PRODUCT IN WOOCOMMERCE OBJECT: {existing_product}")
            if existing_product:
                __logger__.info(
                    f"FOUND EXISTING: {existing_product['name']}"
                )
                wc_product_id = existing_product["id"]
        elif odoo_product.slug:
            # Search by slug is DISABLED - it's broken and returns same product for all slugs
            # This was causing multiple Odoo products to sync to the same WooCommerce ID
            __logger__.info(
                f"Product not synced. Searching by slug: {odoo_product.slug}"
            )
            existing_product = find_woocommerce_product_by_slug(
                odoo_product.slug, wcapi=wcapi
            )
            if existing_product:
                __logger__.info(
                    f"FOUND EXISTING: {existing_product['name']}"
                )
                wc_product_id = existing_product["id"]
        # Convert Pydantic model to dict for API
        product_data = wc_product_data.model_dump(exclude_none=True)
        __logger__.info(f"SLUG: {odoo_product.slug}")
        __logger__.info(f"sku: {odoo_product.default_code}")
        __logger__.info(
            f"Categories in product_data: {product_data.get('categories')}")
        __logger__.info(f"WC_Product_ID: {wc_product_id}")
        if wc_product_id:
            # CONFLICT VALIDATION: Check if this WooCommerce ID is already assigned to another Odoo product
            if sync_repo:
                existing_mapping = sync_repo.get_product_sync_by_wc_id(wc_product_id, instance_id)
                if existing_mapping and existing_mapping.odoo_id != odoo_product.id:
                    __logger__.error(
                        f"CONFLICT: WooCommerce ID {wc_product_id} already mapped to Odoo product "
                        f"{existing_mapping.odoo_id}. Cannot map to {odoo_product.id}."
                    )
                    result.success = False
                    result.action = "error"
                    result.message = (
                        f"WooCommerce product {wc_product_id} already synced to "
                        f"different Odoo product (ID: {existing_mapping.odoo_id})"
                    )
                    return result
            
            # Product exists in WooCommerce
            result.woocommerce_id = wc_product_id

            if update_existing:
                # Update existing product
                __logger__.info(
                    f"Updating WooCommerce product ID: {wc_product_id}: Odoo ID {odoo_product.id}")
                updated_product = wc_request(
                    "PUT",
                    f"products/{wc_product_id}",
                    params=product_data,
                    wcapi=wcapi
                )
                __logger__.info(
                    f"WooCommerce product updated: {updated_product['name']}")
                result.success = True
                result.action = "updated"
                result.message = f"Product updated: {updated_product['name']}"
                result.woocommerce_id = updated_product["id"]

                # Update sync timestamps
                if db:
                    odoo_write_date = None
                    if hasattr(odoo_product, 'write_date') and odoo_product.write_date:
                        try:
                            odoo_write_date = datetime.fromisoformat(
                                str(odoo_product.write_date).replace(" ", "T")
                            )
                        except:
                            pass

                    sync_repo.update_product_sync_timestamps(
                        odoo_id=odoo_product.id,
                        instance_id=instance_id,
                        odoo_name=odoo_product.name,
                        wc_id=updated_product["id"],
                        odoo_write_date=odoo_write_date,
                        last_synced_at=datetime.now(),
                        published=updated_product.get("status") == "publish",
                        needs_sync=False,
                        updated=True,
                        message=result.message
                    )
                else:
                    __logger__.info(
                        "No DB session provided, skipping sync timestamp update.")
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Product exists, update disabled"
        else:
            # Product doesn't exist
            if create_if_not_exists:
                # Create new product
                new_product = wc_request(
                    "POST", "products", params=product_data, wcapi=wcapi
                )
                
                # CONFLICT VALIDATION: Check if newly created WC ID conflicts with existing mapping
                if sync_repo and new_product.get("id"):
                    existing_mapping = sync_repo.get_product_sync_by_wc_id(new_product["id"], instance_id)
                    if existing_mapping and existing_mapping.odoo_id != odoo_product.id:
                        __logger__.error(
                            f"CONFLICT AFTER CREATE: WooCommerce ID {new_product['id']} already mapped to "
                            f"Odoo product {existing_mapping.odoo_id}. New product created but cannot sync."
                        )
                        result.success = False
                        result.action = "error"
                        result.message = (
                            f"WooCommerce product {new_product['id']} already synced to "
                            f"different Odoo product (ID: {existing_mapping.odoo_id})"
                        )
                        return result
                
                result.success = True
                result.action = "created"
                result.message = f"Product created: {new_product['name']}"
                result.woocommerce_id = new_product["id"]

                # Update sync timestamps
                if db:
                    odoo_write_date = None
                    if hasattr(odoo_product, 'write_date') and odoo_product.write_date:
                        try:
                            odoo_write_date = datetime.fromisoformat(
                                str(odoo_product.write_date).replace(" ", "T")
                            )
                        except:
                            pass
                    __logger__.info(
                        f"Updating sync timestamps for created product ID {new_product['id']}")
                    sync_repo.update_product_sync_timestamps(
                        odoo_id=odoo_product.id,
                        instance_id=instance_id,
                        odoo_name=odoo_product.name,
                        wc_id=new_product["id"],
                        odoo_write_date=odoo_write_date,
                        last_synced_at=datetime.now(),
                        published=new_product.get("status") == "publish",
                        needs_sync=False,
                        created=True,
                        message=result.message
                    )
                else:
                    __logger__.info(
                        "No DB session provided, skipping sync timestamp update.")
            else:
                result.success = True
                result.action = "skipped"
                result.message = "Product doesn't exist, creation disabled"

    except IntegrityError as e:
        # Database constraint violation (duplicate WooCommerce ID)
        if db:
            db.rollback()
        result.success = False
        result.action = "error"
        result.message = "Database constraint error: WooCommerce ID already assigned to another product"
        result.error_details = str(e)
        __logger__.error(f"IntegrityError syncing product {odoo_product.id}: {e}")
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
        __logger__.error(f"Error syncing product {odoo_product.name}: {e}")
    finally:
        # ALWAYS release the lock
        if lock:
            try:
                lock.release()
                __logger__.info(f"Released lock for product {odoo_product.id}")
            except Exception as e:
                __logger__.warning(f"Error releasing lock: {e}")

    return result
