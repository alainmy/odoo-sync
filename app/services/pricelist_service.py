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

logger = logging.getLogger(__name__)


class PricelistService:
    """Service for managing pricelist synchronization."""
    
    def __init__(self, db: Session):
        self.db = db
        self.pricelist_repo = PricelistSyncRepository(db)
        self.product_repo = ProductSyncRepository(db)
    
    def get_odoo_product_price(
        self,
        odoo_client,
        product_id: int,
        pricelist_id: Optional[int] = None
    ) -> Optional[float]:
        """
        Get product price from Odoo based on pricelist.
        
        Args:
            odoo_client: Odoo XML-RPC client
            product_id: Odoo product.product ID
            pricelist_id: Odoo pricelist ID (None = default list_price)
            
        Returns:
            Price as float or None
        """
        try:
            if not pricelist_id:
                # Get default list price
                product = odoo_client.search_read_sync(
                    'product.product',
                    domain=[('id', '=', product_id)],
                    fields=['list_price'],
                    limit=1
                )
                if product:
                    return float(product[0].get('list_price', 0))
                return None
            
            # Get price from pricelist
            # Note: We need to get pricelist items that match this product
            pricelist_items = odoo_client.search_read_sync(
                'product.pricelist.item',
                domain=[
                    ('pricelist_id', '=', pricelist_id),
                    '|',
                    ('product_id', '=', product_id),
                    ('product_tmpl_id.product_variant_ids', 'in', [product_id])
                ],
                fields=['fixed_price', 'price_discount', 'compute_price'],
                limit=1
            )
            
            if pricelist_items:
                item = pricelist_items[0]
                if item.get('compute_price') == 'fixed':
                    return float(item.get('fixed_price', 0))
                elif item.get('compute_price') == 'percentage':
                    # Get base price and apply discount
                    product = odoo_client.search_read_sync(
                        'product.product',
                        domain=[('id', '=', product_id)],
                        fields=['list_price'],
                        limit=1
                    )
                    if product:
                        base_price = float(product[0].get('list_price', 0))
                        discount = float(item.get('price_discount', 0))
                        return base_price * (1 - discount / 100)
            
            # Fallback to list_price if no pricelist item found
            product = odoo_client.search_read_sync(
                'product.product',
                domain=[('id', '=', product_id)],
                fields=['list_price'],
                limit=1
            )
            if product:
                return float(product[0].get('list_price', 0))
            
            return None
            
        except Exception as e:
            logger.error(
                f"Error getting Odoo price for product {product_id}, "
                f"pricelist {pricelist_id}: {e}"
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
            active_pricelists = self.pricelist_repo.get_active_by_instance(instance_id)
            
            if not active_pricelists:
                result.message = "No active pricelists configured"
                logger.warning(f"No active pricelists for instance {instance_id}")
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
            logger.error(f"Error syncing prices for product {odoo_product_id}: {e}")
        
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
