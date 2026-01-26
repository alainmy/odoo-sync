"""
Helper functions for product synchronization tasks.
Extracted to improve code readability and maintainability.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.crud.odoo import OdooClient
from app.services.product_variants import (
    has_variants,
    validate_attributes_synced,
    build_wc_attributes_for_product,
    sync_product_variations_sync
)

logger = logging.getLogger(__name__)


def normalize_many2one_field(
    key: str,
    value: List,
    normalized_data: Dict,
    odoo_config: Dict
) -> None:
    """Normaliza campos many2one de Odoo"""
    if key == 'categ_id' and len(value) == 2:
        normalized_data['categ_id'] = value[0] if isinstance(value[0], int) else None
        normalized_data['categ_name'] = value[1] if len(value) > 1 else None
        logger.debug(
            f"Extracted category: ID={normalized_data['categ_id']}, "
            f"Name={normalized_data['categ_name']}"
        )
    elif key == 'product_tag_ids' and value:
        normalized_data[key] = fetch_and_normalize_tags(value, odoo_config)
    elif len(value) == 2 and isinstance(value[0], int):
        normalized_data[key] = value[0]
    else:
        normalized_data[key] = value


def fetch_and_normalize_tags(tag_ids: List, odoo_config: Dict) -> List[Dict]:
    """Consulta y normaliza tags desde Odoo"""
    if not tag_ids:
        return []
    
    if isinstance(tag_ids[0], int):
        logger.debug(f"Fetching tag names from Odoo for IDs: {tag_ids}")
        try:
            odoo_client = OdooClient(
                odoo_config["url"],
                odoo_config["db"],
                odoo_config["username"],
                odoo_config["password"]
            )
            tags_data = odoo_client.search_read_sync(
                'product.tag',
                [['id', 'in', tag_ids]],
                ['id', 'name']
            )
            normalized = [
                {
                    "id": tag.get('id'),
                    "name": tag.get('name', ''),
                    "ks_woo_id": None
                }
                for tag in tags_data
            ]
            logger.debug(f"Fetched {len(normalized)} tags from Odoo")
            return normalized
        except Exception as e:
            logger.error(f"Error fetching tags from Odoo: {e}", exc_info=True)
            return []
    elif isinstance(tag_ids[0], list):
        return [
            {
                "id": tag[0] if isinstance(tag, list) and len(tag) > 0 else tag,
                "name": tag[1] if isinstance(tag, list) and len(tag) > 1 else "",
                "ks_woo_id": None
            }
            for tag in tag_ids
        ]
    return []


def normalize_odoo_product_data(
    odoo_product_data: Dict[str, Any],
    odoo_config: Dict
) -> Dict[str, Any]:
    """
    Normaliza datos de producto de Odoo.
    Convierte False a None, procesa many2one, many2many, etc.
    """
    normalized_data = {}
    
    for key, value in odoo_product_data.items():
        if value is False:
            normalized_data[key] = None
        elif isinstance(value, list):
            normalize_many2one_field(key, value, normalized_data, odoo_config)
        else:
            normalized_data[key] = value
    
    return normalized_data


def create_wc_api_client(wc_config: Optional[Dict[str, str]]):
    """Crea cliente WooCommerce API desde configuración"""
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


def prepare_variable_product_data(
    normalized_data: Dict[str, Any],
    instance_id: int,
    odoo_config: Dict[str, str],
    db: Session
) -> Tuple[bool, Optional[List[Dict]], Optional[Dict]]:
    """
    Valida y prepara datos para producto variable.
    
    Returns:
        (is_variable, product_attributes, error_dict or None)
    """
    if not has_variants(normalized_data):
        return False, None, None
    
    logger.info("Product has variants, validating attributes...")
    
    # Initialize Odoo client
    odoo_client = OdooClient(
        url=odoo_config["url"],
        db=odoo_config["db"],
        username=odoo_config["username"],
        password=odoo_config["password"]
    )
    
    # Validate attributes
    attribute_line_ids = normalized_data.get('attribute_line_ids', [])
    validation = validate_attributes_synced(
        attribute_line_ids=attribute_line_ids,
        instance_id=instance_id,
        db=db,
        odoo_client=odoo_client
    )
    
    if not validation["valid"]:
        error_msg = (
            f"Cannot sync variable product: "
            f"{len(validation['missing_attributes'])} attributes not synced"
        )
        logger.error(error_msg)
        logger.error(f"Missing attributes: {validation['missing_attributes']}")
        logger.error(f"Missing values: {validation['missing_values']}")
        
        return False, None, {
            "message": error_msg,
            "missing_attributes": validation['missing_attributes'],
            "missing_values": validation['missing_values']
        }
    
    # Build attributes
    product_attributes = build_wc_attributes_for_product(
        attribute_line_ids=attribute_line_ids,
        instance_id=instance_id,
        db=db,
        odoo_client=odoo_client
    )
    
    logger.info(f"Product configured as variable with {len(product_attributes)} attributes")
    return True, product_attributes, None


def sync_product_variations(
    odoo_product_id: int,
    wc_product_id: int,
    odoo_client,
    db: Session,
    wcapi,
    instance_id: int
) -> Dict[str, Any]:
    """
    Sincroniza variantes de un producto variable.
    
    Returns:
        Dict con resultado de sincronización de variantes
    """
    logger.info(f"Syncing variations for variable product {wc_product_id}...")
    
    try:
        variation_result = sync_product_variations_sync(
            odoo_client=odoo_client,
            template_id=odoo_product_id,
            wc_parent_id=wc_product_id,
            db=db,
            wcapi=wcapi,
            instance_id=instance_id
        )
        
        total = variation_result.get('total_variations', 0)
        synced = variation_result.get('synced', 0)
        failed = variation_result.get('failed', 0)
        
        if not variation_result.get('success', False):
            logger.warning(f"Some variations failed: {failed}/{total}")
        else:
            logger.info(f"All {synced} variations synced successfully")
        
        return variation_result
        
    except Exception as e:
        logger.error(f"Error syncing variations: {e}", exc_info=True)
        return {
            "success": False,
            "total_variations": 0,
            "synced": 0,
            "failed": 0,
            "errors": [str(e)]
        }
