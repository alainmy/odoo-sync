"""WooCommerce shipping method management."""

import logging
from typing import Any, Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from woocommerce import API
import redis
from redis.lock import Lock as RedisLock
from datetime import datetime

from app.models.shipping_method_sync import ShippingMethodSync
from app.repositories import ShippingMethodRepository
from app.services.woocommerce.client import wc_request
from app.core.config import settings
from app.crud.odoo import OdooClient
from app.crud import instance as crud_instance
from app.utils.odoo_helpers import OdooDataNormalizer

__logger__ = logging.getLogger(__name__)

# Initialize Redis client for distributed locks
try:
    redis_client = redis.Redis.from_url(
        settings.celery_broker_url, decode_responses=True)
    __logger__.info("Redis client initialized for distributed locks")
except Exception as e:
    __logger__.warning(
        f"Failed to initialize Redis client: {e}. Locks will be disabled.")
    redis_client = None

# Default shipping zone name - can be configured
DEFAULT_SHIPPING_ZONE_NAME = getattr(settings, 'DEFAULT_WOCOMMERCE_SHIPPING_ZONE', 'Default Zone')


def normalize_odoo_carrier(odoo_carrier: dict) -> dict:
    """
    Normalize Odoo delivery carrier data for WooCommerce compatibility.
    
    Args:
        odoo_carrier: Raw carrier data from Odoo
        
    Returns:
        Normalized carrier dictionary
    """
    normalizer = OdooDataNormalizer
    return {
        "id": odoo_carrier.get("id"),
        "name": normalizer.normalize_string(odoo_carrier.get("name")),
        "fixed_price": normalizer.normalize_float(odoo_carrier.get("fixed_price")),
        "amount": normalizer.normalize_float(odoo_carrier.get("amount")),
        "free_over": normalizer.normalize_float(odoo_carrier.get("free_over")),
        "product_id": normalizer.normalize_many2one(odoo_carrier.get("product_id")),
        "country_ids": normalizer.normalize_many2many(odoo_carrier.get("country_ids")),
        "state_ids": normalizer.normalize_many2many(odoo_carrier.get("state_ids")),
        "write_date": normalizer.normalize_date(odoo_carrier.get("write_date"))
    }


async def get_active_shipping_zone_id(wcapi: API) -> Optional[int]:
    """
    Get the active shipping zone ID from WooCommerce.
    If no zone exists, creates the default one.
    
    Args:
        wcapi: WooCommerce API client
        
    Returns:
        Shipping zone ID or None if failed
    """
    try:
        # Try to find the default shipping zone by name
        zone = find_woocommerce_shipping_zone_by_name(
            DEFAULT_SHIPPING_ZONE_NAME, wcapi=wcapi
        )
        
        if zone:
            return zone["id"]
        
        # If not found, create the default shipping zone
        __logger__.info(f"Creating default shipping zone: {DEFAULT_SHIPPING_ZONE_NAME}")
        zone_data = {
            "name": DEFAULT_SHIPPING_ZONE_NAME,
            "order": 0
        }
        
        # Create the zone using WooCommerce API
        created_zone = wc_request(
            "POST", 
            "shipping/zones", 
            params=zone_data, 
            wcapi=wcapi
        )
        
        if created_zone and "id" in created_zone:
            __logger__.info(f"Created shipping zone with ID: {created_zone['id']}")
            return created_zone["id"]
        else:
            __logger__.error("Failed to create shipping zone")
            return None
        
    except Exception as e:
        __logger__.error(f"Error getting/creating shipping zone: {e}")
        return None


async def background_shipping_sync(task_id: str, wcapi=None):
    """
    Background task for full shipping method sync from Odoo to WooCommerce.
    
    Args:
        task_id: Unique task ID for tracking
        wcapi: WooCommerce API client (optional, will try to get from active instance if not provided)
    """
    from app.services.woocommerce import SHIPPING_TASKS
    from app.db.session import get_db
    from app.models.admin import Admin
    from app.auth.oauth2 import get_current_user
    
    try:
        SHIPPING_TASKS[task_id]["status"] = "running"
        SHIPPING_TASKS[task_id]["processed"] = 0
        
        __logger__.info(f"Starting background shipping sync for task {task_id}")
        
        # Get database session
        db = next(get_db())
        
        # Get active instance - for background tasks we need to handle this differently
        # In a real implementation, we'd pass the instance_id or user info to the task
        # For now, we'll get the first active instance as a fallback
        try:
            from app.crud import instance as crud_instance
            # We'll need a user - for background tasks, we might need to use a system user
            # or store the user info when the task is created
            # For now, let's get the first admin user as fallback
            admin_user = db.query(Admin).filter(Admin.is_active == True).first()
            if admin_user:
                instance = crud_instance.get_active_instance(db, user_id=admin_user.id)
                if not instance:
                    # If no active instance, get the first one
                    instance = crud_instance.get_instance_by_name(db, "default")  # or get first instance
                    if not instance:
                        instances = crud_instance.get_all_instances(db, limit=1)
                        instance = instances[0] if instances else None
            else:
                instance = None
        except Exception as e:
            __logger__.warning(f"Could not get instance for background task: {e}")
            instance = None
            
        if not instance:
            __logger__.error("No WooCommerce instance found for shipping sync")
            SHIPPING_TASKS[task_id]["status"] = "error"
            SHIPPING_TASKS[task_id]["error"] = "No WooCommerce instance found"
            return
            
        instance_id = instance.id
        
        # Get WooCommerce API client if not provided
        if wcapi is None:
            try:
                from app.services.woocommerce.client import get_wc_api_from_instance_config
                # Get instance config - this would need to be implemented
                # For now, we'll try to get it from the instance record
                wc_config = {
                    "url": instance.wc_url,
                    "consumer_key": instance.wc_consumer_key,
                    "consumer_secret": instance.wc_consumer_secret
                }
                wcapi = get_wc_api_from_instance_config(wc_config)
            except Exception as e:
                __logger__.warning(f"Could not get WC API from instance config: {e}")
                # Fallback to settings
                wcapi = None
                
        if wcapi is None:
            __logger__.error("Could not initialize WooCommerce API client")
            SHIPPING_TASKS[task_id]["status"] = "error"
            SHIPPING_TASKS[task_id]["error"] = "Could not initialize WooCommerce API client"
            return
        
        # Get or create default shipping zone
        zone_id = await get_active_shipping_zone_id(wcapi)
        if not zone_id:
            __logger__.error("Could not get or create shipping zone")
            SHIPPING_TASKS[task_id]["status"] = "error"
            SHIPPING_TASKS[task_id]["error"] = "Could not get or create shipping zone"
            return
        
        # Initialize Odoo client
        try:
            odoo_client = OdooClient(
                instance.odoo_url,
                instance.odoo_db,
                instance.odoo_username,
                instance.odoo_password
            )
            uid = await odoo_client.odoo_authenticate()
            if not uid:
                raise Exception("Could not authenticate with Odoo")
        except Exception as e:
            __logger__.error(f"Could initialize Odoo client: {e}")
            SHIPPING_TASKS[task_id]["status"] = "error"
            SHIPPING_TASKS[task_id]["error"] = f"Could not initialize Odoo client: {e}"
            return
        
        # Get delivery carriers from Odoo
        try:
            carriers_result = await odoo_client.search_read(
                uid,
                "delivery.carrier",
                domain=[],
                limit=1000,  # Reasonable limit
                fields=[
                    "id",
                    "name",
                    "fixed_price",
                    "amount",
                    "free_over",
                    "product_id",
                    "country_ids",
                    "state_ids",
                    "write_date"
                ]
            )
            
            if carriers_result.get("error"):
                raise Exception(f"Odoo error: {carriers_result['error']['message']}")
                
            carriers = carriers_result.get("result", [])
            __logger__.info(f"Found {len(carriers)} delivery carriers in Odoo")
            
        except Exception as e:
            __logger__.error(f"Error fetching carriers from Odoo: {e}")
            SHIPPING_TASKS[task_id]["status"] = "error"
            SHIPPING_TASKS[task_id]["error"] = f"Error fetching carriers from Odoo: {e}"
            return
        
        # Initialize repository
        sync_repo = ShippingMethodRepository(db)
        
        # Process each carrier
        processed_count = 0
        for carrier_data in carriers:
            try:
                # Normalize carrier data
                normalized_carrier = normalize_odoo_carrier(carrier_data)
                
                # Skip if no name
                if not normalized_carrier.get("name"):
                    __logger__.warning(f"Skipping carrier {carrier_data.get('id')} - no name")
                    continue
                
                # Prepare WooCommerce method data
                wc_method_data = {
                    "title": normalized_carrier.get("name"),
                    "method_id": "flat_rate",  # Default to flat rate - would need mapping
                    "enabled": True,
                    "tax_status": "taxable",
                    "instance_id": instance_id  # Not part of WooCommerce API but useful for tracking
                }
                
                # Add cost if available
                if normalized_carrier.get("fixed_price") is not None:
                    wc_method_data["cost"] = str(normalized_carrier.get("fixed_price"))
                elif normalized_carrier.get("amount") is not None:
                    wc_method_data["cost"] = str(normalized_carrier.get("amount"))
                else:
                    wc_method_data["cost"] = "0.00"  # Default cost
                
                # Sync the shipping method
                sync_result = create_or_update_woocommerce_shipping_method(
                    odoo_carrier=normalized_carrier,
                    wc_method_data=wc_method_data,
                    instance_id=instance_id,
                    zone_id=zone_id,
                    create_if_not_exists=True,
                    update_existing=True,
                    db=db,
                    wcapi=wcapi
                )
                
                if sync_result.get("success"):
                    processed_count += 1
                    __logger__.info(f"Synced carrier {normalized_carrier.get('name')}: {sync_result.get('message')}")
                    
                    # Update sync timestamps in database
                    if sync_result.get("woocommerce_id"):
                        sync_repo.update_shipping_method_sync_timestamps(
                            odoo_id=normalized_carrier.get("id"),
                            instance_id=instance_id,
                            odoo_name=normalized_carrier.get("name"),
                            wc_id=sync_result.get("woocommerce_id"),
                            odoo_write_date=normalized_carrier.get("write_date"),
                            last_synced_at=datetime.now(),
                            created=sync_result.get("action") == "created",
                            updated=sync_result.get("action") == "updated",
                            message=sync_result.get("message")
                        )
                else:
                    __logger__.warning(f"Failed to sync carrier {normalized_carrier.get('name')}: {sync_result.get('message')}")
                
            except Exception as e:
                __logger__.error(f"Error processing carrier {carrier_data.get('id', 'unknown')}: {e}")
                continue  # Continue with next carrier
        
        SHIPPING_TASKS[task_id]["status"] = "finished"
        SHIPPING_TASKS[task_id]["processed"] = processed_count
        
        __logger__.info(f"Background shipping sync completed for task {task_id}. Processed {processed_count} carriers.")
        
    except Exception as e:
        __logger__.error(f"Error in background shipping sync: {e}")
        SHIPPING_TASKS[task_id]["status"] = "error"
        SHIPPING_TASKS[task_id]["error"] = str(e)
    finally:
        # Close database session
        try:
            db.close()
        except:
            pass


def find_woocommerce_shipping_zone_by_name(zone_name: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a shipping zone in WooCommerce by name.

    Args:
        zone_name: Shipping zone name to search
        wcapi: WooCommerce API client

    Returns:
        Shipping zone dict if found, None otherwise
    """
    if not zone_name:
        return None

    try:
        zones = wc_request("GET", "shipping/zones",
                           params={"name": zone_name, "per_page": 1}, wcapi=wcapi)
        if zones and len(zones) > 0:
            # Validate exact name match
            __logger__.info(f"Zones found for name {zone_name}: {len(zones)}")
            found_zone = zones[0]
            if found_zone:
                if found_zone.get("name") == zone_name:
                    __logger__.info(f"Exact zone name match found: {zone_name}")
                    return found_zone
                else:
                    __logger__.warning(
                        f"Zone name mismatch: searched '{zone_name}', got '{found_zone.get('name')}'. "
                        f"Ignoring fuzzy result.")
                    return None
        return None
    except Exception as e:
        __logger__.info(f"Error searching shipping zone by name {zone_name}: {e}")
        return None


def find_woocommerce_shipping_zone_by_id(zone_id: int, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a shipping zone in WooCommerce by ID.

    Args:
        zone_id: Shipping zone ID
        wcapi: WooCommerce API client

    Returns:
        Shipping zone dict if found, None otherwise
    """
    if not zone_id:
        return None

    try:
        zone = wc_request("GET", f"shipping/zones/{zone_id}", wcapi=wcapi)
        return zone if zone else None
    except Exception as e:
        __logger__.error(f"Error searching shipping zone by ID {zone_id}: {e}")
        return None


def find_woocommerce_shipping_method_in_zone(method_id: int, zone_id: int, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a shipping method in a specific shipping zone by method ID.

    Args:
        method_id: Shipping method ID
        zone_id: Shipping zone ID
        wcapi: WooCommerce API client

    Returns:
        Shipping method dict if found, None otherwise
    """
    if not method_id or not zone_id:
        return None

    try:
        methods = wc_request("GET", f"shipping/zones/{zone_id}/methods",
                             params={"per_page": 100}, wcapi=wcapi)
        if methods:
            for method in methods:
                if method.get("id") == method_id:
                    return method
        return None
    except Exception as e:
        __logger__.error(f"Error searching shipping method {method_id} in zone {zone_id}: {e}")
        return None


def find_woocommerce_shipping_method_by_name_in_zone(method_name: str, zone_id: int, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """
    Search for a shipping method in a specific shipping zone by name.

    Args:
        method_name: Shipping method name to search
        zone_id: Shipping zone ID
        wcapi: WooCommerce API client

    Returns:
        Shipping method dict if found, None otherwise
    """
    if not method_name or not zone_id:
        return None

    try:
        methods = wc_request("GET", f"shipping/zones/{zone_id}/methods",
                             params={"per_page": 100}, wcapi=wcapi)
        if methods:
            for method in methods:
                if method.get("name", "").lower() == method_name.lower():
                    return method
        return None
    except Exception as e:
        __logger__.error(f"Error searching shipping method by name {method_name} in zone {zone_id}: {e}")
        return None


def create_or_update_woocommerce_shipping_method(
    odoo_carrier: Dict[str, Any],
    wc_method_data: Dict[str, Any],
    instance_id: int,
    zone_id: int,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    db: Session = None,
    wcapi: API = None
) -> Dict[str, Any]:
    """
    Create or update a shipping method in WooCommerce.

    Args:
        odoo_carrier: Odoo delivery carrier object
        wc_method_data: WooCommerce shipping method data
        instance_id: WooCommerce instance ID
        zone_id: Shipping zone ID where the method should exist
        create_if_not_exists: Create if method doesn't exist in zone
        update_existing: Update if method exists in zone
        db: Database session
        wcapi: WooCommerce API client

    Returns:
        Dict with sync operation details (similar to ProductSyncResult)
    """
    __logger__.info(
        f"CREDENTIALS WC API: {wcapi.url if wcapi else 'from factory'}, "
        f"{wcapi.consumer_key if wcapi else 'from factory'}, "
        f"{wcapi.consumer_secret if wcapi else 'from factory'}")
    
    result = {
        "odoo_id": odoo_carrier.get("id"),
        "odoo_name": odoo_carrier.get("name"),
        "success": False,
        "action": "skipped",
        "message": "Not processed",
        "woocommerce_id": None,
        "error_details": None
    }

    # DISTRIBUTED LOCK: Prevent race conditions with Redis
    lock_key = f"shipping_sync:{odoo_carrier.get('id')}:{instance_id}:{zone_id}"
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
                    f"Could not acquire lock for shipping carrier {odoo_carrier.get('id')}, skipping sync"
                )
                result["success"] = False
                result["action"] = "skipped"
                result["message"] = "Another worker is syncing this shipping method"
                return result
            __logger__.info(f"Acquired lock for shipping carrier {odoo_carrier.get('id')}")

        # First search in sync table (faster)
        sync_repo = ShippingMethodRepository(db) if db else None
        sync_method = None
        if db:
            # Assuming we have a method to get sync by odoo_id and instance_id
            # This would need to be implemented in the repository
            pass
            
        wc_method_id = None
        if sync_method:
            # Already synced, use ID directly
            __logger__.info(
                f"Shipping method already synced. WooCommerce ID: {sync_method.woocommerce_id}"
            )
            existing_method = find_woocommerce_shipping_method_in_zone(
                sync_method.woocommerce_id, zone_id, wcapi=wcapi
            )
            if existing_method:
                __logger__.info(
                    f"Found existing WooCommerce shipping method by ID: {existing_method['name']}"
                )
                wc_method_id = sync_method.woocommerce_id
        elif odoo_carrier.get("name"):
            # Not in sync table, search in WooCommerce by name in the specific zone
            __logger__.info(
                f"Shipping method. Searching by name: {odoo_carrier.get('name')} in zone {zone_id}"
            )
            existing_method = find_woocommerce_shipping_method_by_name_in_zone(
                odoo_carrier.get("name"), zone_id, wcapi=wcapi
            )
            if existing_method:
                __logger__.info(
                    f"FOUND EXISTING: {existing_method['name']}"
                )
                wc_method_id = existing_method["id"]

        if wc_method_id:
            # CONFLICT VALIDATION: Check if this WooCommerce ID is already assigned to another Odoo carrier
            if sync_repo and db:
                # This would need a method to check by woocommerce_id in the repository
                pass

            # Shipping method exists in WooCommerce zone
            result["woocommerce_id"] = wc_method_id

            if update_existing:
                # Update existing shipping method
                __logger__.info(
                    f"Updating WooCommerce shipping method ID: {wc_method_id}: Odoo ID {odoo_carrier.get('id')}"
                )
                updated_method = None
                try:
                    updated_method = wc_request(
                        "PUT",
                        f"shipping/zones/{zone_id}/methods/{wc_method_id}",
                        params=wc_method_data,
                        wcapi=wcapi
                    )
                except Exception as e:
                    __logger__.error(f"Error updating WooCommerce shipping method: {e}")
                    result["success"] = False
                    result["action"] = "error"
                    result["message"] = f"Error updating WooCommerce shipping method: {e}"
                    result["error_details"] = str(e)
                    return result
                __logger__.info(
                    f"WooCommerce shipping method updated: {updated_method['name']}"
                )
                result["success"] = True
                result["action"] = "updated"
                result["message"] = f"Shipping method updated: {updated_method['name']}"
                result["woocommerce_id"] = updated_method["id"]

                # Update sync timestamps
                if db and sync_repo:
                    # Update shipping method sync details
                    pass
            else:
                result["success"] = True
                result["action"] = "skipped"
                result["message"] = "Shipping method exists, update disabled"
        else:
            # Shipping method doesn't exist in the zone
            if create_if_not_exists:
                # Create new shipping method in the zone
                try:
                    new_method = wc_request(
                        "POST",
                        f"shipping/zones/{zone_id}/methods",
                        params=wc_method_data,
                        wcapi=wcapi
                    )
                    # CONFLICT VALIDATION: Check if newly created WC ID conflicts with existing mapping
                    if sync_repo and db and new_method.get("id"):
                        # This would need a method to check by woocommerce_id in the repository
                        pass

                    result["success"] = True
                    result["action"] = "created"
                    result["message"] = f"Shipping method created: {new_method['name']}"
                    result["woocommerce_id"] = new_method["id"]

                    # Update sync timestamps
                    if db and sync_repo and new_method.get("id"):
                        # Update shipping method sync details
                        pass
                except Exception as e:
                    __logger__.error(f"Error creating shipping method: {str(e)}")
                    result["success"] = False
                    result["action"] = "error"
                    result["message"] = f"Error creating shipping method: {str(e)}"
                    result["error_details"] = str(e)
                    return result

            else:
                result["success"] = True
                result["action"] = "skipped"
                result["message"] = "Shipping method doesn't exist, creation disabled"

    except IntegrityError as e:
        # Database constraint violation (duplicate WooCommerce ID)
        if db:
            db.rollback()
        result["success"] = False
        result["action"] = "error"
        result["message"] = "Database constraint error: WooCommerce ID already assigned to another shipping method"
        result["error_details"] = str(e)
        __logger__.error(
            f"IntegrityError syncing shipping method {odoo_carrier.get('id')}: {e}")
    except HTTPException as e:
        result["success"] = False
        result["action"] = "error"
        result["message"] = f"HTTP Error: {e.detail}"
        result["error_details"] = str(e)
    except Exception as e:
        result["success"] = False
        result["action"] = "error"
        result["message"] = f"Unexpected error: {str(e)}"
        result["error_details"] = str(e)
        __logger__.error(f"Error syncing shipping method {odoo_carrier.get('name')}: {e}")
    finally:
        # ALWAYS release the lock
        if lock:
            try:
                lock.release()
                __logger__.info(f"Released lock for shipping carrier {odoo_carrier.get('id')}")
            except Exception as e:
                __logger__.warning(f"Error releasing lock: {e}")

    return result