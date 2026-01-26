"""WooCommerce services package."""

from app.services.woocommerce.client import (
    wc_request,
    wc_request_with_logging,
    wc_get,
    wc_post,
    wc_put,
    wc_delete,
    wc_request_post,
    get_wc_api_from_instance_config,
    get_wc_api_from_active_instance
)

from app.services.woocommerce.products import (
    find_woocommerce_product_by_sku,
    find_woocommerce_product_by_id,
    create_or_update_woocommerce_product
)

from app.services.woocommerce.categories import (
    manage_category_for_export,
    find_woocommerce_category_by_name,
    find_category_by_slug,
    create_or_update_woocommerce_category,
    build_category_chain,
    category_for_export
)

from app.services.woocommerce.tags import (
    manage_tags_for_export
)

from app.services.woocommerce.converters import (
    woocommerce_type_to_odoo_type,
    odoo_product_to_woocommerce
)

from app.services.woocommerce.utils import (
    fetch_wc_product,
    background_full_sync,
    push_to_odoo
)

__all__ = [
    # Client
    'wc_request',
    'wc_request_with_logging',
    'wc_get',
    'wc_post',
    'wc_put',
    'wc_delete',
    'wc_request_post',
    'get_wc_api_from_instance_config',
    'get_wc_api_from_active_instance',
    # Products
    'find_woocommerce_product_by_sku',
    'find_woocommerce_product_by_id',
    'create_or_update_woocommerce_product',
    # Categories
    'manage_category_for_export',
    'find_woocommerce_category_by_name',
    'find_category_by_slug',
    'create_or_update_woocommerce_category',
    'build_category_chain',
    'category_for_export',
    # Tags
    'manage_tags_for_export',
    # Converters
    'woocommerce_type_to_odoo_type',
    'odoo_product_to_woocommerce',
    # Utils
    'fetch_wc_product',
    'background_full_sync',
    'push_to_odoo',
]
