"""Constants for Odoo operations."""

from enum import Enum


class OdooProductType:
    """Odoo product type constants."""
    PRODUCT = "product"  # Stockable Product
    CONSU = "consu"      # Consumable
    SERVICE = "service"   # Service


class OdooInvoiceState:
    """Odoo invoice state constants."""
    DRAFT = "draft"
    POSTED = "posted"
    CANCEL = "cancel"


class OdooOrderState:
    """Odoo sale order state constants."""
    DRAFT = "draft"
    SENT = "sent"
    SALE = "sale"
    DONE = "done"
    CANCEL = "cancel"


class OdooPartnerType:
    """Odoo partner type constants."""
    CONTACT = "contact"
    INVOICE = "invoice"
    DELIVERY = "delivery"
    OTHER = "other"
    PRIVATE = "private"


class OdooModel:
    """Odoo model name constants."""
    PRODUCT_PRODUCT = "product.product"
    PRODUCT_TEMPLATE = "product.template"
    PRODUCT_CATEGORY = "product.category"
    PRODUCT_TAG = "product.tag"
    RES_PARTNER = "res.partner"
    SALE_ORDER = "sale.order"
    SALE_ORDER_LINE = "sale.order.line"
    ACCOUNT_MOVE = "account.move"
    ACCOUNT_MOVE_LINE = "account.move.line"
    STOCK_PICKING = "stock.picking"
    STOCK_MOVE = "stock.move"


class OdooField:
    """Common Odoo field names."""
    ID = "id"
    NAME = "name"
    DISPLAY_NAME = "display_name"
    CREATE_DATE = "create_date"
    WRITE_DATE = "write_date"
    ACTIVE = "active"
    COMPANY_ID = "company_id"
    
    # Product specific
    DEFAULT_CODE = "default_code"  # SKU
    BARCODE = "barcode"
    LIST_PRICE = "list_price"
    STANDARD_PRICE = "standard_price"
    CATEG_ID = "categ_id"
    QTY_AVAILABLE = "qty_available"
    VIRTUAL_AVAILABLE = "virtual_available"
