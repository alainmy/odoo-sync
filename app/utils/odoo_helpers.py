"""Helper functions and classes for Odoo data normalization."""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class OdooDataNormalizer:
    """Normalizes Odoo data to a consistent format."""
    
    @staticmethod
    def normalize_many2one(value: Any) -> Optional[int]:
        """
        Normalize many2one field from Odoo.
        
        Args:
            value: Can be False, None, int, or [id, name]
            
        Returns:
            int or None: Extracted ID or None
        """
        if value is False or value is None:
            return None
        if isinstance(value, list) and len(value) >= 1:
            return value[0]
        if isinstance(value, int):
            return value
        return None
    
    @staticmethod
    def normalize_many2many(value: Any) -> List[int]:
        """
        Normalize many2many field from Odoo.
        
        Args:
            value: Can be False, None, or list of IDs
            
        Returns:
            List of IDs (empty list if None/False)
        """
        if value is False or value is None:
            return []
        if isinstance(value, list):
            return value
        return []
    
    @staticmethod
    def normalize_boolean(value: Any) -> bool:
        """
        Normalize boolean field from Odoo (handles False as False).
        
        Args:
            value: Any value
            
        Returns:
            bool: Normalized boolean value
        """
        if value is False or value is None:
            return False
        return bool(value)
    
    @staticmethod
    def normalize_string(value: Any) -> Optional[str]:
        """
        Normalize string field from Odoo (False becomes None).
        
        Args:
            value: Any value
            
        Returns:
            str or None: Normalized string or None
        """
        if value is False or value is None:
            return None
        return str(value)
    
    @staticmethod
    def normalize_float(value: Any) -> float:
        """
        Normalize float field from Odoo.
        
        Args:
            value: Any value
            
        Returns:
            float: Normalized float (0.0 if None/False)
        """
        if value is False or value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    @staticmethod
    def normalize_date(value: Any) -> Optional[str]:
        """
        Normalize date/datetime field from Odoo.
        
        Args:
            value: Can be False, None, or datetime string
            
        Returns:
            str or None: ISO format date string or None
        """
        if value is False or value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        return None
    
    @staticmethod
    def normalize_product(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a complete Odoo product dictionary.
        
        Args:
            data: Raw product data from Odoo
            
        Returns:
            Dict with normalized fields
        """
        normalizer = OdooDataNormalizer
        
        return {
            "id": data.get("id"),
            "name": normalizer.normalize_string(data.get("name")),
            "default_code": normalizer.normalize_string(data.get("default_code")),
            "list_price": normalizer.normalize_float(data.get("list_price")),
            "standard_price": normalizer.normalize_float(data.get("standard_price")),
            "type": normalizer.normalize_string(data.get("type", "product")),
            "categ_id": normalizer.normalize_many2one(data.get("categ_id")),
            "barcode": normalizer.normalize_string(data.get("barcode")),
            "description": normalizer.normalize_string(data.get("description")),
            "description_sale": normalizer.normalize_string(data.get("description_sale")),
            "weight": normalizer.normalize_float(data.get("weight")),
            "volume": normalizer.normalize_float(data.get("volume")),
            "active": normalizer.normalize_boolean(data.get("active", True)),
            "sale_ok": normalizer.normalize_boolean(data.get("sale_ok", True)),
            "purchase_ok": normalizer.normalize_boolean(data.get("purchase_ok", True)),
            "qty_available": normalizer.normalize_float(data.get("qty_available")),
            "virtual_available": normalizer.normalize_float(data.get("virtual_available")),
            "image_1920": normalizer.normalize_string(data.get("image_1920")),
            "image_medium": normalizer.normalize_string(data.get("image_128")),
            "product_tag_ids": normalizer.normalize_many2many(data.get("product_tag_ids")),
            "write_date": normalizer.normalize_date(data.get("write_date")),
            "create_date": normalizer.normalize_date(data.get("create_date")),
        }
    
    @staticmethod
    def normalize_category(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a complete Odoo category dictionary.
        
        Args:
            data: Raw category data from Odoo
            
        Returns:
            Dict with normalized fields
        """
        normalizer = OdooDataNormalizer
        
        return {
            "id": data.get("id"),
            "name": normalizer.normalize_string(data.get("name")),
            "complete_name": normalizer.normalize_string(data.get("complete_name")),
            "parent_id": normalizer.normalize_many2one(data.get("parent_id")),
            "parent_path": normalizer.normalize_string(data.get("parent_path")),
            "child_id": normalizer.normalize_many2many(data.get("child_id")),
            "write_date": normalizer.normalize_date(data.get("write_date")),
        }
    
    @staticmethod
    def normalize_tag(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a complete Odoo tag dictionary.
        
        Args:
            data: Raw tag data from Odoo
            
        Returns:
            Dict with normalized fields
        """
        normalizer = OdooDataNormalizer
        
        return {
            "id": data.get("id"),
            "name": normalizer.normalize_string(data.get("name")),
            "color": normalizer.normalize_float(data.get("color")),
            "write_date": normalizer.normalize_date(data.get("write_date")),
        }
    
    @staticmethod
    def normalize_order(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a complete Odoo order dictionary.
        
        Args:
            data: Raw order data from Odoo
            
        Returns:
            Dict with normalized fields
        """
        normalizer = OdooDataNormalizer
        
        return {
            "id": data.get("id"),
            "name": normalizer.normalize_string(data.get("name")),
            "partner_id": normalizer.normalize_many2one(data.get("partner_id")),
            "date_order": normalizer.normalize_date(data.get("date_order")),
            "amount_total": normalizer.normalize_float(data.get("amount_total")),
            "state": normalizer.normalize_string(data.get("state")),
            "order_line": normalizer.normalize_many2many(data.get("order_line")),
            "write_date": normalizer.normalize_date(data.get("write_date")),
        }
    
    @staticmethod
    def normalize_batch(items: List[Dict[str, Any]], item_type: str = "product") -> List[Dict[str, Any]]:
        """
        Normalize a batch of Odoo items.
        
        Args:
            items: List of raw items from Odoo
            item_type: Type of items ('product', 'category', 'tag', 'order')
            
        Returns:
            List of normalized items
        """
        normalizer = OdooDataNormalizer
        
        type_map = {
            "product": normalizer.normalize_product,
            "category": normalizer.normalize_category,
            "tag": normalizer.normalize_tag,
            "order": normalizer.normalize_order,
        }
        
        normalize_func = type_map.get(item_type)
        if not normalize_func:
            logger.warning(f"Unknown item type: {item_type}, returning raw data")
            return items
        
        return [normalize_func(item) for item in items]


def extract_category_path(complete_name: Optional[str]) -> List[str]:
    """
    Extract category path from Odoo complete_name.
    
    Args:
        complete_name: Category complete name (e.g., "Parent / Child / Grandchild")
        
    Returns:
        List of category names in path order
    """
    if not complete_name:
        return []
    
    # Split by ' / ' (Odoo separator) and strip whitespace
    return [name.strip() for name in complete_name.split('/')]


def build_category_hierarchy(categories: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    Build a hierarchical structure from flat category list.
    
    Args:
        categories: Flat list of normalized categories
        
    Returns:
        Dict mapping category IDs to enriched category data with children
    """
    category_map = {}
    
    for cat in categories:
        cat_id = cat["id"]
        category_map[cat_id] = {
            **cat,
            "children": []
        }
    
    # Build parent-child relationships
    for cat in categories:
        parent_id = cat.get("parent_id")
        if parent_id and parent_id in category_map:
            category_map[parent_id]["children"].append(cat["id"])
    
    return category_map
