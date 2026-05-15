"""WooCommerce tax management."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from woocommerce import API
import redis
from redis.lock import Lock as RedisLock

from app.models.tax_sync import TaxSync
from app.models.admin import WooCommerceInstance
from app.services.woocommerce.client import wc_request, wc_request_with_logging
from app.repositories.tax_sync_repository import TaxSyncRepository
from app.core.config import settings
from app.crud.odoo import OdooClient

__logger__ = logging.getLogger(__name__)

try:
    redis_client = redis.Redis.from_url(
        settings.celery_broker_url, decode_responses=True)
    __logger__.info("Redis client initialized for tax locks")
except Exception as e:
    __logger__.warning(
        f"Failed to initialize Redis client: {e}. Tax locks will be disabled.")
    redis_client = None


def sync_tax_to_woocommerce(
    tax_data: dict,
    db: Session = None,
    wcapi: API = None,
    instance_id: Optional[int] = None,
    odoo_config: Optional[Dict[str, str]] = None,
    create_if_not_exists: bool = True,
    update_existing: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Synchronize a tax from Odoo to WooCommerce.

    Args:
        tax_data: Dictionary containing tax details from Odoo
        db: Database session
        wcapi: WooCommerce API client
        instance_id: WooCommerce instance ID
        odoo_config: Odoo configuration
        create_if_not_exists: Create tax if it doesn't exist
        update_existing: Update tax if it exists

    Returns:
        Dict with sync result or None on error
    """
    lock_key = f"tax_sync:{tax_data.get('id')}:{instance_id}"
    lock_timeout = 300
    lock = None

    try:
        if redis_client:
            lock = RedisLock(redis_client, lock_key,
                             timeout=lock_timeout, blocking_timeout=10)
            acquired = lock.acquire(blocking=True)
            if not acquired:
                __logger__.warning(
                    f"Could not acquire lock for tax {tax_data.get('id')}, skipping sync"
                )
                return None
            __logger__.info(f"Acquired lock for tax {tax_data.get('id')}")

        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first() if db and instance_id else None
        odoo_client = OdooClient(**odoo_config) if odoo_config else None
        repo = TaxSyncRepository(db)
        existing_sync = repo.get_by_odoo_id_and_instance(
            tax_data.get("id"), instance_id
        ) if db and instance_id else None

        woocommerce_id = existing_sync.woocommerce_id if existing_sync else None

        tax_name = tax_data.get("name", "Tax")
        tax_rate = float(tax_data.get("amount", 0))
        tax_description = tax_data.get("description", "")
        price_include = tax_data.get("price_include", False)
        type_tax_use = tax_data.get("type_tax_use", "sale")
        country_id = tax_data.get("country_id", None)
        country_name = None
        country_code = None
        tax_scope = None
        if country_id:
            __logger__.info(f"Tax {tax_name} has country_id {country_id}, fetching country details from Odoo")
            country = odoo_client.search_read_sync(
                model="res.country",
                domain=[["id", "=", country_id[0]]],
                fields=["id", "name", "code"],
                limit=1
            )
            if country:
                country_name = country[0].get("name", "")
                country_code = country[0].get("code", "")
                tax_scope = f"{country_name} ({country_code}) Sales Tax"
                __logger__.info(f"Country found in Odoo: {country_name} ({country_code}) Sales Tax")
            else:
                tax_scope = "Sales Tax"
        else:
            __logger__.info(f"Tax {tax_name} does not have a country_id, defaulting tax_scope to 'Sales Tax'")
            tax_scope = "Sales Tax"

        tax_scope = "sales" if type_tax_use == "sale" else "purchase" if type_tax_use == "purchase" else "none"

        __logger__.info(
            f"Preparing to export tax {tax_name} "
            f"(Odoo ID: {tax_data.get('id')}, Rate: {tax_rate}%) to WooCommerce"
        )

        tax_data_wc = {
            "rate": str(tax_rate),
            "name": f"{country_code} - {tax_name} -- {tax_rate}",
            "country": country_code,
            "shipping": False,
        }

        if woocommerce_id and update_existing:
            __logger__.info(
                f"Tax {tax_name} exists in WooCommerce (ID: {woocommerce_id}), updating")

            existing_in_woo = None
            try:
                existing_in_woo = wc_request(
                    "GET",
                    f"taxes/{woocommerce_id}",
                    wcapi=wcapi
                )
            except Exception as e:
                __logger__.warning(f"Could not fetch WC tax {woocommerce_id}: {e}")

            if existing_in_woo and existing_in_woo.get("rate") != str(tax_rate):
                __logger__.info(
                    f"Updating tax {tax_name} in WooCommerce (ID: {woocommerce_id})")
                response = wc_request(
                    "PUT",
                    f"taxes/{woocommerce_id}",
                    params=tax_data_wc,
                    wcapi=wcapi
                )
                action = "updated"
            else:
                __logger__.info(f"Tax {tax_name} already up to date")
                action = "skipped"
        else:
            __logger__.info(
                f"Tax {tax_name} not found in WooCommerce, creating new")

            existing_in_woo = None
            if not woocommerce_id and create_if_not_exists:
                search_params = {"limit": 10}
                try:
                    response = wc_request(
                        "GET", "taxes", params=search_params, wcapi=wcapi
                    )
                    if response:
                        for t in response:
                            if t.get("name", "").lower() == tax_name.lower():
                                existing_in_woo = t
                                woocommerce_id = t["id"]
                                __logger__.info(
                                    f"Found existing tax in WooCommerce by name: {woocommerce_id}")
                                break
                except Exception as e:
                    __logger__.warning(f"Error searching existing tax: {e}")

            if existing_in_woo:
                __logger__.info(f"Tax {tax_name} found in WooCommerce (ID: {woocommerce_id}), updating")
                response = wc_request(
                    "PUT",
                    f"taxes/{woocommerce_id}",
                    params=tax_data_wc,
                    wcapi=wcapi
                )
                action = "updated"
            elif create_if_not_exists:
                __logger__.info(f"Creating tax {tax_data_wc} in WooCommerce")
                response = wc_request(
                    "POST", "taxes", params=tax_data_wc, wcapi=wcapi
                )
                __logger__.info(f"TAX RESPONSE: {response}")

                woocommerce_id = response["id"]
                action = "created"
                __logger__.info(f"Created new tax in WooCommerce: ID {woocommerce_id}")
            else:
                __logger__.warning(f"Tax {tax_name} not created, create_if_not_exists is False")
                return None

        if not woocommerce_id:
            __logger__.error(f"Failed to get/create WooCommerce tax ID for {tax_name}")
            return None

        if db and instance_id:
            if existing_sync:
                repo.update_sync_record(
                    existing_sync,
                    woocommerce_id=woocommerce_id,
                    created=(action == "created"),
                    updated=(action == "updated"),
                    rate=tax_rate,
                    amount=tax_data.get("amount"),
                    price_include=price_include,
                    tax_scope=tax_scope,
                    type_tax_use=type_tax_use,
                    last_synced_at=datetime.utcnow(),
                    message=f"Tax {action}: {tax_name}",
                    error=False
                )
                __logger__.info(f"Updated existing sync record for tax {tax_data.get('id')} -> WC {woocommerce_id}")
            else:
                try:
                    new_sync = repo.create_sync_record(
                        odoo_id=tax_data.get("id"),
                        woocommerce_id=woocommerce_id,
                        odoo_name=tax_name,
                        odoo_description=tax_description,
                        instance_id=instance_id,
                        rate=tax_rate,
                        amount=tax_data.get("amount"),
                        price_include=price_include,
                        tax_scope=tax_scope,
                        type_tax_use=type_tax_use,
                        active=tax_data.get("active", True),
                        created=(action == "created"),
                        last_synced_at=datetime.utcnow(),
                        message=f"Tax created: {tax_name}"
                    )
                    __logger__.info(f"Created new sync record for tax {tax_data.get('id')} -> WC {woocommerce_id}")
                except IntegrityError as ie:
                    db.rollback()
                    __logger__.warning(f"Race condition detected: sync record already exists for tax {tax_data.get('id')}, fetching and updating")
                    existing_sync = repo.get_by_odoo_id_and_instance(tax_data.get("id"), instance_id)
                    if existing_sync:
                        repo.update_sync_record(
                            existing_sync,
                            woocommerce_id=woocommerce_id,
                            created=(action == "created"),
                            updated=(action == "updated"),
                            rate=tax_rate,
                            amount=tax_data.get("amount"),
                            price_include=price_include,
                            tax_scope=tax_scope,
                            type_tax_use=type_tax_use,
                            last_synced_at=datetime.utcnow(),
                            message=f"Tax {action} after race condition: {tax_name}",
                            error=False
                        )

        return {
            "success": True,
            "action": action,
            "odoo_id": tax_data.get("id"),
            "woocommerce_id": woocommerce_id,
            "name": tax_name,
            "rate": tax_rate
        }

    except Exception as e:
        __logger__.error(f"Error syncing tax {tax_data.get('name')}: {e}", exc_info=True)

        if db and instance_id and existing_sync:
            try:
                repo.update_sync_record(
                    existing_sync,
                    error=True,
                    message=f"Error syncing tax: {str(e)}",
                    error_details=str(e)
                )
            except Exception:
                pass

        return None

    finally:
        if lock:
            try:
                lock.release()
                __logger__.info(f"Released lock for tax {tax_data.get('id')}")
            except Exception as e:
                __logger__.warning(f"Error releasing tax lock: {e}")


async def find_woocommerce_tax_by_name(name: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """Search for a tax in WooCommerce by exact name."""
    try:
        taxes = wc_request(
            "GET", "taxes",
            params={"limit": 100},
            wcapi=wcapi
        )
        for tax in taxes:
            if tax.get("name", "").lower() == name.lower():
                return tax
        return None
    except Exception as e:
        __logger__.error(f"Error searching tax by name {name}: {e}")
        return None


async def find_woocommerce_tax_by_rate(rate: str, wcapi: API = None) -> Optional[Dict[str, Any]]:
    """Search for a tax in WooCommerce by rate."""
    try:
        taxes = wc_request(
            "GET", "taxes",
            params={"limit": 100},
            wcapi=wcapi
        )
        for tax in taxes:
            if tax.get("rate", "") == rate:
                return tax
        return None
    except Exception as e:
        __logger__.error(f"Error searching tax by rate {rate}: {e}")
        return None


def get_odoo_taxes(
    odoo_client: OdooClient,
    domain: List = None,
    fields: List[str] = None
) -> List[Dict[str, Any]]:
    """
    Get taxes from Odoo.

    Args:
        odoo_client: OdooClient instance
        domain: Domain filter for Odoo search
        fields: Fields to retrieve from Odoo

    Returns:
        List of tax dictionaries
    """
    if fields is None:
        fields = [
            "id",
            "name",
            "amount",
            "description",
            "price_include",
            "type_tax_use",
            "active",
            "write_date"
        ]

    if domain is None:
        domain = [["active", "=", True]]

    try:
        taxes = odoo_client.search_read_sync(
            model="account.tax",
            domain=domain,
            fields=fields
        )
        return taxes if taxes else []
    except Exception as e:
        __logger__.error(f"Error fetching taxes from Odoo: {e}")
        return []


def create_wc_api_client(wc_config: Dict[str, str]):
    """Create WooCommerce API client from configuration."""
    if not wc_config:
        return None

    from woocommerce import API
    return API(
        url=wc_config["url"],
        consumer_key=wc_config["consumer_key"],
        consumer_secret=wc_config["consumer_secret"],
        wp_api=True,
        version="wc/v3",
        timeout=60,
        verify_ssl=False
    )


def normalize_odoo_tax_data(tax_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize tax data from Odoo.

    Args:
        tax_data: Raw tax data from Odoo

    Returns:
        Normalized tax data
    """
    normalized = {}

    for key, value in tax_data.items():
        if value is False:
            normalized[key] = None
        elif isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
            normalized[key] = value[0]
        else:
            normalized[key] = value

    return normalized