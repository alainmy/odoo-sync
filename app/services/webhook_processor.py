"""Service for processing WooCommerce webhook events."""

import hashlib
import hmac
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.admin import WebhookLog, ProductSync, WooCommerceInstance
from app.repositories.webhook_config_repository import WebhookConfigRepository
from app.repositories.order_sync_repository import OrderSyncRepository

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """Service for processing WooCommerce webhooks."""
    
    def __init__(self, db: Session):
        self.db = db
        self.webhook_repo = WebhookConfigRepository(db)
    
    def validate_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str
    ) -> bool:
        """
        Validate WooCommerce webhook signature.
        
        Args:
            payload: Raw request body as bytes
            signature: X-WC-Webhook-Signature header value
            secret: Webhook secret from configuration
            
        Returns:
            True if signature is valid
        """
        try:
            # WooCommerce uses HMAC-SHA256 with base64 encoding
            computed_hash = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).digest()
            
            # Convert to base64
            import base64
            computed_signature = base64.b64encode(computed_hash).decode('utf-8')
            
            is_valid = hmac.compare_digest(computed_signature, signature)
            
            if not is_valid:
                logger.warning(
                    f"Invalid webhook signature. "
                    f"Expected: {computed_signature}, Got: {signature}"
                )
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error validating webhook signature: {e}")
            return False
    
    def calculate_payload_hash(self, payload: Dict[str, Any]) -> str:
        """Calculate SHA256 hash of payload for deduplication."""
        payload_str = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(payload_str.encode()).hexdigest()
    
    def is_duplicate_event(self, event_id: str, payload_hash: str) -> bool:
        """
        Check if webhook event has already been processed.
        
        Args:
            event_id: WooCommerce webhook delivery ID
            payload_hash: SHA256 hash of payload
            
        Returns:
            True if event is duplicate
        """
        existing = self.db.query(WebhookLog).filter(
            (WebhookLog.event_id == event_id) | 
            (WebhookLog.payload_hash == payload_hash)
        ).first()
        
        if existing:
            logger.info(f"Duplicate webhook event detected: {event_id}")
            return True
        
        return False
    
    def log_webhook_event(
        self,
        event_id: str,
        event_type: str,
        instance_id: int,
        payload: Dict[str, Any],
        status: str = "pending"
    ) -> WebhookLog:
        """
        Log webhook event to database.
        
        Args:
            event_id: WooCommerce webhook delivery ID
            event_type: Event topic (e.g., product.created)
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            status: Event status
            
        Returns:
            Created WebhookLog record
        """
        payload_hash = self.calculate_payload_hash(payload)
        
        log_entry = WebhookLog(
            event_id=event_id,
            event_type=event_type,
            instance_id=instance_id,
            payload=payload,
            payload_hash=payload_hash,
            status=status
        )
        
        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)
        
        logger.info(f"Logged webhook event {event_id} ({event_type})")
        return log_entry
    
    def update_webhook_log_status(
        self,
        log_id: int,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Update webhook log status."""
        log_entry = self.db.query(WebhookLog).filter(
            WebhookLog.id == log_id
        ).first()
        
        if log_entry:
            log_entry.status = status
            if error_message:
                log_entry.error_message = error_message
            if status == "completed":
                log_entry.processed_at = datetime.utcnow()
            
            self.db.commit()
    
    def process_product_created(
        self,
        instance_id: int,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process product.created webhook event.
        
        Args:
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        try:
            wc_product_id = payload.get('id')
            product_name = payload.get('name', 'Unknown')
            
            logger.info(
                f"Processing product.created: WC ID {wc_product_id}, "
                f"Name: {product_name}"
            )
            
            # Check if product already synced
            existing = self.db.query(ProductSync).filter(
                ProductSync.woocommerce_id == wc_product_id,
                ProductSync.instance_id == instance_id
            ).first()
            
            if existing:
                logger.info(
                    f"Product {wc_product_id} already synced as Odoo ID {existing.odoo_id}"
                )
                return {
                    'success': True,
                    'message': 'Product already synced',
                    'product_sync_id': existing.id
                }
            
            # Mark for sync or create placeholder
            product_sync = ProductSync(
                woocommerce_id=wc_product_id,
                odoo_name=product_name,
                instance_id=instance_id,
                needs_sync=True,
                message="Created in WooCommerce, pending Odoo sync"
            )
            
            self.db.add(product_sync)
            self.db.commit()
            self.db.refresh(product_sync)
            
            logger.info(f"Product {wc_product_id} marked for Odoo sync")
            
            return {
                'success': True,
                'message': 'Product marked for sync',
                'product_sync_id': product_sync.id
            }
            
        except Exception as e:
            logger.error(f"Error processing product.created: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def process_product_updated(
        self,
        instance_id: int,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process product.updated webhook event.
        
        Args:
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        try:
            wc_product_id = payload.get('id')
            product_name = payload.get('name', 'Unknown')
            
            logger.info(
                f"Processing product.updated: WC ID {wc_product_id}, "
                f"Name: {product_name}"
            )
            
            # Find existing sync record
            product_sync = self.db.query(ProductSync).filter(
                ProductSync.woocommerce_id == wc_product_id,
                ProductSync.instance_id == instance_id
            ).first()
            
            if product_sync:
                # Update sync record
                product_sync.odoo_name = product_name
                product_sync.needs_sync = True
                product_sync.message = "Updated in WooCommerce, pending Odoo sync"
                product_sync.wc_date_updated = datetime.utcnow()
                
                self.db.commit()
                
                logger.info(
                    f"Product {wc_product_id} updated and marked for Odoo sync"
                )
                
                return {
                    'success': True,
                    'message': 'Product updated and marked for sync',
                    'product_sync_id': product_sync.id
                }
            else:
                # Product not synced yet, create new record
                product_sync = ProductSync(
                    woocommerce_id=wc_product_id,
                    odoo_name=product_name,
                    instance_id=instance_id,
                    needs_sync=True,
                    message="Updated in WooCommerce, pending Odoo sync"
                )
                
                self.db.add(product_sync)
                self.db.commit()
                self.db.refresh(product_sync)
                
                logger.info(
                    f"Product {wc_product_id} created and marked for Odoo sync"
                )
                
                return {
                    'success': True,
                    'message': 'Product created and marked for sync',
                    'product_sync_id': product_sync.id
                }
            
        except Exception as e:
            logger.error(f"Error processing product.updated: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def process_product_deleted(
        self,
        instance_id: int,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process product.deleted webhook event.
        
        Args:
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        try:
            wc_product_id = payload.get('id')
            
            logger.info(f"Processing product.deleted: WC ID {wc_product_id}")
            
            # Find and mark product as deleted
            product_sync = self.db.query(ProductSync).filter(
                ProductSync.woocommerce_id == wc_product_id,
                ProductSync.instance_id == instance_id
            ).first()
            
            if product_sync:
                # Mark as needing sync to handle deletion in Odoo
                product_sync.needs_sync = True
                product_sync.message = "Deleted in WooCommerce"
                
                self.db.commit()
                
                logger.info(f"Product {wc_product_id} marked as deleted")
                
                return {
                    'success': True,
                    'message': 'Product marked as deleted',
                    'product_sync_id': product_sync.id
                }
            else:
                logger.warning(
                    f"Product {wc_product_id} not found in sync records"
                )
                return {
                    'success': True,
                    'message': 'Product not in sync records'
                }
            
        except Exception as e:
            logger.error(f"Error processing product.deleted: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def process_order_created(
        self,
        instance_id: int,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process order.created webhook event.
        
        Args:
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            
        Returns:
            Processing result
        """
        try:
            order_sync_repo = OrderSyncRepository(self.db)
            order_id = payload.get('id')
            order_number = payload.get('number')
            
            logger.info(
                f"Processing order.created: WC Order #{order_number} (ID: {order_id})"
            )
            
            # Process order data and create sync record
            
            # Create order sync record
            order_sync = order_sync_repo.add_order_sync(
                woo_id=order_id,
                instance_id=instance_id,
                payload=payload
            )
            
            logger.info(f"Created order sync record: {order_sync.id}")
            
            return {
                'success': True,
                'message': f'Order #{order_number} logged',
                'order_id': order_id
            }
            
        except Exception as e:
            logger.error(f"Error processing order.created: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def process_webhook_event(
        self,
        event_type: str,
        instance_id: int,
        payload: Dict[str, Any],
        log_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Route webhook event to appropriate processor.
        
        Args:
            event_type: Webhook topic (e.g., product.created)
            instance_id: WooCommerce instance ID
            payload: Webhook payload
            log_id: WebhookLog ID for status updates
            
        Returns:
            Processing result
        """
        try:
            # Route to appropriate processor
            if event_type == 'product.created':
                result = self.process_product_created(instance_id, payload)
            elif event_type == 'product.updated':
                result = self.process_product_updated(instance_id, payload)
            elif event_type == 'product.deleted':
                result = self.process_product_deleted(instance_id, payload)
            elif event_type == 'order.created':
                result = self.process_order_created(instance_id, payload)
            elif event_type == 'order.updated':
                result = self.process_order_created(instance_id, payload)  # Reuse for now
            else:
                logger.warning(f"Unhandled webhook event type: {event_type}")
                result = {
                    'success': True,
                    'message': f'Event type {event_type} not yet implemented'
                }
            
            # Update webhook log status
            if log_id:
                status = "completed" if result.get('success') else "failed"
                error_msg = None if result.get('success') else result.get('message')
                self.update_webhook_log_status(log_id, status, error_msg)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing webhook event {event_type}: {e}")
            
            if log_id:
                self.update_webhook_log_status(log_id, "failed", str(e))
            
            return {
                'success': False,
                'message': str(e)
            }
