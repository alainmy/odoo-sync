"""WooCommerce tag management."""

import logging
from datetime import datetime
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from woocommerce import API

from app.models.admin import TagSync
from app.services.woocommerce.client import wc_request

__logger__ = logging.getLogger(__name__)


def manage_tags_for_export(
    product_tags: List[Dict[str, Any]],
    db: Session = None,
    wcapi: API = None,
    instance_id: int = None
) -> List[Dict[str, int]]:
    """
    Manage creation and export of tags to WooCommerce.
    Similar to ks_manage_tags_to_export from Odoo module.
    
    Args:
        product_tags: List of product tags [{"id": 1, "name": "Tag1", "ks_woo_id": None}, ...]
        db: Database session for tracking
        wcapi: WooCommerce API client (uses settings if not provided)
        instance_id: WooCommerce instance ID (for multi-tenancy)
    
    Returns:
        List of tags with WooCommerce IDs [{"id": 456}, ...]
    """
    __logger__.info(f"manage_tags_for_export called with: {product_tags}")
    __logger__.info(
        f"Type of product_tags: {type(product_tags)}, "
        f"Length: {len(product_tags) if product_tags else 0}"
    )
    __logger__.info(f"db session: {db}")
    
    if not product_tags:
        __logger__.warning("product_tags is empty or None")
        return []
    
    data = []
    
    try:
        for tag in product_tags:
            tag_name = tag.get("name") or tag.get("display_name", "")
            slug = tag_name.replace(" ", "-").lower() + str(tag.get("id", ""))
            __logger__.info(f"Processing tag: {tag_name} (slug: {slug})")
            ks_woo_id = tag.get("ks_woo_id")
            
            if ks_woo_id:
                # Tag already has WooCommerce ID, just add it
                data.append({"id": ks_woo_id})
            else:
                # Search tag in WooCommerce by name
                tags_response = wc_request(
                    "GET", "products/tags",
                    params={"slug": slug, "per_page": 100},
                    wcapi=wcapi
                )
                
                found_tag = None
                for wc_tag in tags_response:
                    if wc_tag.get("slug", "").lower() == slug.lower():
                        found_tag = wc_tag
                        break
                
                if found_tag:
                    # Tag exists in WooCommerce
                    data.append({"id": found_tag["id"]})
                    __logger__.info(f"Tag found: {tag_name} (ID: {found_tag['id']})")
                    
                    # Save record for existing tag if not already registered
                    if db and tag.get("id"):
                        try:
                            # Check if record already exists
                            existing_tag_sync = db.query(TagSync).filter(
                                TagSync.odoo_id == tag["id"],
                                TagSync.instance_id == instance_id
                            ).first() if instance_id else db.query(TagSync).filter(
                                TagSync.odoo_id == tag["id"]
                            ).first()
                            
                            if existing_tag_sync:
                                # Update if WooCommerce ID changed
                                if existing_tag_sync.woocommerce_id != found_tag["id"]:
                                    existing_tag_sync.woocommerce_id = found_tag["id"]
                                    existing_tag_sync.updated = True
                                    existing_tag_sync.message = f"Tag ID updated: {tag_name}"
                                    existing_tag_sync.last_synced_at = datetime.utcnow()
                                    db.commit()
                                    __logger__.info(
                                        f"TagSync updated: Odoo {tag['id']} -> "
                                        f"WC {found_tag['id']}"
                                    )
                                else:
                                    __logger__.info(
                                        f"TagSync already exists and is up to date: "
                                        f"Odoo {tag['id']} -> WC {found_tag['id']}"
                                    )
                            else:
                                # Create new record for existing tag
                                tag_sync = TagSync(
                                    odoo_id=tag["id"],
                                    woocommerce_id=found_tag["id"],
                                    instance_id=instance_id,
                                    skipped=True,  # Mark as skipped because it already existed
                                    message=f"Tag already exists: {tag_name}",
                                    last_synced_at=datetime.utcnow()
                                )
                                db.add(tag_sync)
                                db.commit()
                                __logger__.info(
                                    f"TagSync saved for existing tag: "
                                    f"Odoo {tag['id']} -> WC {found_tag['id']}"
                                )
                        except Exception as e:
                            __logger__.error(
                                f"Error saving TagSync for existing tag: {e}"
                            )
                            db.rollback()
                else:
                    # Create new tag in WooCommerce
                    new_tag_data = {
                        "name": tag_name,
                        "slug": slug
                    }
                    
                    new_tag = wc_request(
                        "POST", "products/tags", params=new_tag_data, wcapi=wcapi
                    )
                    data.append({"id": new_tag["id"]})
                    __logger__.info(f"Tag created: {tag_name} (ID: {new_tag['id']})")
                    
                    # Save record for created tag
                    if db and tag.get("id"):
                        try:
                            tag_sync = TagSync(
                                odoo_id=tag["id"],
                                woocommerce_id=new_tag["id"],
                                instance_id=instance_id,
                                created=True,
                                message=f"Tag created: {tag_name}",
                                last_synced_at=datetime.utcnow()
                            )
                            db.add(tag_sync)
                            db.commit()
                            __logger__.info(
                                f"TagSync saved: Odoo {tag['id']} -> WC {new_tag['id']}"
                            )
                        except Exception as e:
                            __logger__.error(f"Error saving TagSync: {e}")
                            db.rollback()
        
        return data
        
    except Exception as e:
        __logger__.error(f"Error handling tags: {e}")
        return []
