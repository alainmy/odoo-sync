"""Service for pricelist synchronization between Odoo and WooCommerce."""

import logging
from typing import Optional, Dict, List, Any
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from woocommerce import API

from app.repositories.pricelist_sync_repository import PricelistSyncRepository
from app.repositories.product_sync_repository import ProductSyncRepository
from app.models.admin import ProductSync
from app.schemas.pricelist_schemas import PriceSyncResult
from app.services.woocommerce.client import wc_request
from app.crud.odoo import OdooClient

logger = logging.getLogger(__name__)


class PricelistService:
    """Service for managing pricelist synchronization."""

    def __init__(self, db: Session):
        self.db = db
        self.pricelist_repo = PricelistSyncRepository(db)
        self.product_repo = ProductSyncRepository(db)

    #

    def get_odoo_product_price(
        self,
        odoo_client: OdooClient,
        product_id: int,
        product_tmpl_id: Optional[int] = None,
        pricelist_id: Optional[int] = None,
        qty: float = 1.0,
        partner_id: Optional[int] = None,
        date: Optional[str] = None
    ) -> Optional[float]:
        """
        Get product price from Odoo based on pricelist.
        Replicates Odoo's pricelist computation logic.
        
        Args:
            odoo_client: Odoo XML-RPC client
            product_id: Odoo product.product ID
            product_tmpl_id: Odoo product.template ID (optional, will be fetched if not provided)
            pricelist_id: Odoo pricelist ID (None = default list_price)
            qty: Quantity (affects price computation)
            partner_id: Partner ID (for partner-specific pricelists)
            date: Date for price computation (YYYY-MM-DD format)
            
        Returns:
            Price as float or None
        """
        try:
            # 1. Get product data if template_id not provided
            if not product_tmpl_id:
                product_data = odoo_client.search_read_sync(
                    'product.product',
                    domain=[('id', '=', product_id)],
                    fields=['list_price', 'standard_price',
                            'product_tmpl_id', 'categ_id'],
                    limit=1
                )
                if not product_data:
                    logger.warning(f"Product {product_id} not found in Odoo")
                    return None

                product = product_data[0]
                product_tmpl_id = product.get('product_tmpl_id')[0] if isinstance(
                    product.get('product_tmpl_id'), list
                ) else product.get('product_tmpl_id')
                categ_id = product.get('categ_id')[0] if isinstance(
                    product.get('categ_id'), list
                ) else product.get('categ_id')
            else:
                # Get full product data
                product_data = odoo_client.search_read_sync(
                    'product.product',
                    domain=[('id', '=', product_id)],
                    fields=['list_price', 'standard_price', 'categ_id'],
                    limit=1
                )
                if not product_data:
                    return None

                product = product_data[0]
                categ_id = product.get('categ_id')[0] if isinstance(
                    product.get('categ_id'), list
                ) else product.get('categ_id')

            base_list_price = float(product.get('list_price', 0))
            base_standard_price = float(product.get('standard_price', 0))

            # 2. If no pricelist, return list_price
            if not pricelist_id:
                logger.info(
                    f"No pricelist specified, returning list_price: {base_list_price}")
                return base_list_price

            # 3. Build domain to search pricelist items (Odoo priority order)
            # Priority:
            # 1. Product variant (applied_on = '0_product_variant')
            # 2. Product template (applied_on = '1_product')
            # 3. Product category (applied_on = '2_product_category')
            # 4. All products (applied_on = '3_global')

            domain = [
                ('pricelist_id', '=', pricelist_id),
                '|', ('date_start', '=', False), ('date_start', '<=', date or False),
                '|', ('date_end', '=', False), ('date_end', '>=', date or False),
                '|', ('min_quantity', '=', False), ('min_quantity', '<=', qty),
            ]

            # Add product-specific filters with OR logic
            product_domain = [
                '|',
                '|',
                '|',
                # Variant specific
                '&',
                ('applied_on', '=', '0_product_variant'),
                ('product_id', '=', product_id),
                # Template specific
                '&',
                ('applied_on', '=', '1_product'),
                ('product_tmpl_id', '=', product_tmpl_id),
                # Category specific
                '&',
                ('applied_on', '=', '2_product_category'),
                ('categ_id', '=', categ_id),
                # Global
                ('applied_on', '=', '3_global'),
            ]

            full_domain = domain + product_domain

            logger.info(f"Searching pricelist items with domain: {full_domain}")

            # 4. Search pricelist items, ordered by priority
            pricelist_items = odoo_client.search_read_sync(
                'product.pricelist.item',
                domain=full_domain,
                fields=[
                    'applied_on',
                    'compute_price',
                    'fixed_price',
                    'percent_price',
                    'price_discount',  # Old field, kept for compatibility
                    'price_surcharge',
                    'price_min_margin',
                    'price_max_margin',
                    'base',
                    'base_pricelist_id',
                    'min_quantity',
                ],
                order='applied_on, min_quantity desc, categ_id desc, id',
                limit=10  # Get multiple to find the best match
            )

            if not pricelist_items:
                logger.info(
                    f"No pricelist items found for product {product_id} "
                    f"in pricelist {pricelist_id}, returning list_price: {base_list_price}"
                )
                return base_list_price

            # 5. Apply the first matching rule (Odoo logic)
            # The query already ordered by priority, so we take the first valid one
            selected_item = None
            for item in pricelist_items:
                min_qty = item.get('min_quantity', 0)
                if qty >= min_qty:
                    selected_item = item
                    break

            if not selected_item:
                selected_item = pricelist_items[0]

            logger.info(f"Selected pricelist item: {selected_item}")

            # 6. Calculate price based on compute_price type
            compute_price = selected_item.get('compute_price', 'fixed')

            # 6.1 Get base price according to 'base' field
            base_type = selected_item.get('base', 'list_price')

            if base_type == 'list_price':
                base_price = base_list_price
            elif base_type == 'standard_price':
                base_price = base_standard_price
            elif base_type == 'pricelist':
                # Recursive call to another pricelist
                base_pricelist_id = selected_item.get('base_pricelist_id')
                if isinstance(base_pricelist_id, list):
                    base_pricelist_id = base_pricelist_id[0]

                if base_pricelist_id and base_pricelist_id != pricelist_id:
                    base_price = self.get_odoo_product_price(
                        odoo_client,
                        product_id,
                        product_tmpl_id,
                        base_pricelist_id,
                        qty,
                        partner_id,
                        date
                    ) or base_list_price
                else:
                    base_price = base_list_price
            else:
                base_price = base_list_price

            logger.info(f"Base price ({base_type}): {base_price}")

            # 6.2 Calculate final price
            final_price = base_price

            if compute_price == 'fixed':
                # Fixed price
                final_price = float(selected_item.get('fixed_price', 0))
                logger.info(f"Using fixed price: {final_price}")

            elif compute_price == 'percentage':
                # Percentage discount/surcharge
                # percent_price: negative = discount, positive = surcharge
                percent_price = float(selected_item.get('percent_price', 0))

                # Fallback to old field if percent_price is 0
                if percent_price == 0:
                    price_discount = float(selected_item.get('price_discount', 0))
                    percent_price = -price_discount  # Old field was positive for discount

                final_price = base_price * (1 + percent_price / 100)
                logger.info(
                    f"Percentage computation: {base_price} * (1 + {percent_price}/100) = {final_price}"
                )

            elif compute_price == 'formula':
                # Formula: (base_price * (1 + percent)) + surcharge
                percent_price = float(selected_item.get('percent_price', 0))
                price_surcharge = float(selected_item.get('price_surcharge', 0))

                final_price = (base_price * (1 + percent_price / 100)
                            ) + price_surcharge
                logger.info(
                    f"Formula computation: ({base_price} * (1 + {percent_price}/100)) + "
                    f"{price_surcharge} = {final_price}"
                )

                # Apply margins if defined
                price_min_margin = float(selected_item.get('price_min_margin', 0))
                price_max_margin = float(selected_item.get('price_max_margin', 0))

                if price_min_margin and final_price < base_standard_price + price_min_margin:
                    final_price = base_standard_price + price_min_margin
                    logger.info(f"Applied min margin: {final_price}")

                if price_max_margin and final_price > base_standard_price + price_max_margin:
                    final_price = base_standard_price + price_max_margin
                    logger.info(f"Applied max margin: {final_price}")

            # 7. Ensure price is not negative
            final_price = max(0, final_price)

            logger.info(
                f"Final price for product {product_id} with pricelist {pricelist_id}: {final_price}"
            )

            return round(final_price, 2)

        except Exception as e:
            logger.error(
                f"Error getting Odoo price for product {product_id}, "
                f"pricelist {pricelist_id}: {e}",
                exc_info=True
            )
            return None

    def sync_product_prices(
        self,
        odoo_client,
        odoo_product_id: int,
        instance_id: int,
        wcapi: Optional[API] = None
    ) -> PriceSyncResult:
        """
        Sync prices for a single product based on active pricelists.

        Args:
            odoo_client: Odoo XML-RPC client
            odoo_product_id: Odoo product ID
            instance_id: WooCommerce instance ID
            wcapi: WooCommerce API client

        Returns:
            PriceSyncResult with sync status
        """
        result = PriceSyncResult(
            odoo_product_id=odoo_product_id,
            woocommerce_id=None,
            success=False,
            synced_prices={},
            message="Not processed"
        )

        try:
            # Get product sync record
            product_sync = self.db.query(ProductSync).filter(
                ProductSync.odoo_id == odoo_product_id,
                ProductSync.instance_id == instance_id
            ).first()

            if not product_sync or not product_sync.woocommerce_id:
                result.message = f"Product {odoo_product_id} not synced to WooCommerce"
                logger.warning(result.message)
                return result

            result.woocommerce_id = product_sync.woocommerce_id

            # Get active pricelists for this instance
            active_pricelists = self.pricelist_repo.get_active_by_instance(
                instance_id)

            if not active_pricelists:
                result.message = "No active pricelists configured"
                logger.warning(
                    f"No active pricelists for instance {instance_id}")
                return result

            # Build price data for WooCommerce
            wc_price_data = {}
            meta_data = []

            for pricelist_sync in active_pricelists:
                price = self.get_odoo_product_price(
                    odoo_client,
                    odoo_product_id,
                    pricelist_sync.odoo_pricelist_id
                )

                if price is None:
                    logger.warning(
                        f"Could not get price for product {odoo_product_id}, "
                        f"pricelist {pricelist_sync.odoo_pricelist_id}"
                    )
                    continue

                price_str = str(round(price, 2))

                if pricelist_sync.price_type == 'regular':
                    wc_price_data['regular_price'] = price_str
                    result.synced_prices['regular_price'] = price

                elif pricelist_sync.price_type == 'sale':
                    wc_price_data['sale_price'] = price_str
                    result.synced_prices['sale_price'] = price

                elif pricelist_sync.price_type == 'meta' and pricelist_sync.meta_key:
                    meta_data.append({
                        'key': pricelist_sync.meta_key,
                        'value': price_str
                    })
                    result.synced_prices[pricelist_sync.meta_key] = price

            if meta_data:
                wc_price_data['meta_data'] = meta_data

            if not wc_price_data:
                result.message = "No prices to sync"
                return result

            # Update product in WooCommerce
            logger.info(
                f"Updating WooCommerce product {product_sync.woocommerce_id} "
                f"with prices: {wc_price_data}"
            )

            response = wc_request(
                "PUT",
                f"products/{product_sync.woocommerce_id}",
                params=wc_price_data,
                wcapi=wcapi
            )

            if response:
                result.success = True
                result.message = f"Synced {len(result.synced_prices)} price(s)"
                logger.info(
                    f"Successfully synced prices for product {odoo_product_id} "
                    f"-> WC {product_sync.woocommerce_id}"
                )
            else:
                result.message = "WooCommerce update failed"

        except Exception as e:
            result.success = False
            result.message = f"Error syncing prices: {str(e)}"
            result.error_details = str(e)
            logger.error(
                f"Error syncing prices for product {odoo_product_id}: {e}")

        return result

    def sync_all_product_prices(
        self,
        odoo_client,
        instance_id: int,
        product_ids: Optional[List[int]] = None,
        wcapi: Optional[API] = None
    ) -> Dict[str, Any]:
        """
        Sync prices for all products (or specific products) in an instance.

        Args:
            odoo_client: Odoo XML-RPC client
            instance_id: WooCommerce instance ID
            product_ids: Optional list of specific product IDs to sync
            wcapi: WooCommerce API client

        Returns:
            Dict with sync statistics
        """
        results = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'details': []
        }

        try:
            # Get products to sync
            query = self.db.query(ProductSync).filter(
                ProductSync.instance_id == instance_id,
                ProductSync.woocommerce_id.isnot(None)
            )

            if product_ids:
                query = query.filter(ProductSync.odoo_id.in_(product_ids))

            products = query.all()
            results['total'] = len(products)

            logger.info(
                f"[PRICELIST SERVICE] Starting price sync for {results['total']} products "
                f"in instance {instance_id}"
            )

            if results['total'] == 0:
                logger.warning(
                    f"[PRICELIST SERVICE] No products found to sync for instance {instance_id}. "
                    f"Make sure products are synced to WooCommerce first."
                )

            for product in products:
                result = self.sync_product_prices(
                    odoo_client,
                    product.odoo_id,
                    instance_id,
                    wcapi
                )

                if result.success:
                    results['successful'] += 1
                else:
                    results['failed'] += 1

                # Convert Pydantic model to dict for JSON serialization
                results['details'].append(result.model_dump())

            logger.info(
                f"Price sync completed: {results['successful']} successful, "
                f"{results['failed']} failed"
            )

        except Exception as e:
            logger.error(f"Error in bulk price sync: {e}")
            results['error'] = str(e)

        return results
