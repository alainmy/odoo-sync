"""Constants for WooCommerce operations."""

from enum import Enum


class WCProductType:
    """WooCommerce product type constants."""
    SIMPLE = "simple"
    GROUPED = "grouped"
    EXTERNAL = "external"
    VARIABLE = "variable"


class WCProductStatus:
    """WooCommerce product status constants."""
    DRAFT = "draft"
    PENDING = "pending"
    PRIVATE = "private"
    PUBLISH = "publish"


class WCStockStatus:
    """WooCommerce stock status constants."""
    IN_STOCK = "instock"
    OUT_OF_STOCK = "outofstock"
    ON_BACKORDER = "onbackorder"


class WCTaxStatus:
    """WooCommerce tax status constants."""
    TAXABLE = "taxable"
    SHIPPING = "shipping"
    NONE = "none"


class WCOrderStatus:
    """WooCommerce order status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    ON_HOLD = "on-hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"
    TRASH = "trash"


class WCWebhookTopic:
    """WooCommerce webhook topic constants."""
    # Products
    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"
    PRODUCT_DELETED = "product.deleted"
    PRODUCT_RESTORED = "product.restored"
    
    # Orders
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_DELETED = "order.deleted"
    ORDER_RESTORED = "order.restored"
    
    # Customers
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_DELETED = "customer.deleted"
    
    # Coupons
    COUPON_CREATED = "coupon.created"
    COUPON_UPDATED = "coupon.updated"
    COUPON_DELETED = "coupon.deleted"
    COUPON_RESTORED = "coupon.restored"


class WCApiVersion:
    """WooCommerce API version constants."""
    V3 = "wc/v3"
    V2 = "wc/v2"
    V1 = "wc/v1"


class WCImagePosition:
    """WooCommerce image position constants."""
    MAIN = 0
    GALLERY_1 = 1
    GALLERY_2 = 2
    GALLERY_3 = 3
