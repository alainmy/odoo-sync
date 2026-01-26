"""Service for webhook management and WooCommerce API integration."""

import logging
import time
import requests
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from woocommerce import API

from app.repositories.webhook_config_repository import WebhookConfigRepository
from app.schemas.webhook_schemas import (
    WebhookConfigCreate,
    WebhookTestResult,
    WebhookSyncResult,
    WooCommerceWebhook
)
from app.services.woocommerce.client import wc_request

logger = logging.getLogger(__name__)


class WebhookService:
    """Service for managing webhooks and synchronizing with WooCommerce."""
    
    def __init__(self, db: Session):
        self.db = db
        self.webhook_repo = WebhookConfigRepository(db)
    
    def create_webhook_in_woocommerce(
        self,
        wcapi: API,
        webhook_data: WebhookConfigCreate
    ) -> Optional[Dict[str, Any]]:
        """
        Create a webhook in WooCommerce via API.
        
        Args:
            wcapi: WooCommerce API client
            webhook_data: Webhook configuration
            
        Returns:
            WooCommerce webhook data or None if failed
        """
        try:
            payload = {
                "name": webhook_data.name or f"Webhook {webhook_data.topic}",
                "topic": webhook_data.topic,
                "delivery_url": webhook_data.delivery_url,
                "secret": webhook_data.secret or "",
                "status": webhook_data.status,
            }
            
            logger.info(f"Creating webhook in WooCommerce: {payload}")
            
            response = wc_request(
                "POST",
                "webhooks",
                params=payload,
                wcapi=wcapi
            )
            
            if response:
                logger.info(f"Successfully created webhook {response.get('id')} in WooCommerce")
                return response
            else:
                logger.error("Failed to create webhook in WooCommerce")
                return None
                
        except Exception as e:
            logger.error(f"Error creating webhook in WooCommerce: {e}")
            return None
    
    def update_webhook_in_woocommerce(
        self,
        wcapi: API,
        wc_webhook_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a webhook in WooCommerce via API.
        
        Args:
            wcapi: WooCommerce API client
            wc_webhook_id: WooCommerce webhook ID
            update_data: Data to update
            
        Returns:
            Updated webhook data or None if failed
        """
        try:
            logger.info(f"Updating webhook {wc_webhook_id} in WooCommerce")
            
            response = wc_request(
                "PUT",
                f"webhooks/{wc_webhook_id}",
                params=update_data,
                wcapi=wcapi
            )
            
            if response:
                logger.info(f"Successfully updated webhook {wc_webhook_id}")
                return response
            else:
                logger.error(f"Failed to update webhook {wc_webhook_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error updating webhook {wc_webhook_id}: {e}")
            return None
    
    def delete_webhook_in_woocommerce(
        self,
        wcapi: API,
        wc_webhook_id: int
    ) -> bool:
        """
        Delete a webhook in WooCommerce via API.
        
        Args:
            wcapi: WooCommerce API client
            wc_webhook_id: WooCommerce webhook ID
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            logger.info(f"Deleting webhook {wc_webhook_id} from WooCommerce")
            
            response = wc_request(
                "DELETE",
                f"webhooks/{wc_webhook_id}",
                params={"force": True},
                wcapi=wcapi
            )
            
            if response:
                logger.info(f"Successfully deleted webhook {wc_webhook_id}")
                return True
            else:
                logger.error(f"Failed to delete webhook {wc_webhook_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting webhook {wc_webhook_id}: {e}")
            return False
    
    def get_webhooks_from_woocommerce(
        self,
        wcapi: API
    ) -> List[WooCommerceWebhook]:
        """
        Get all webhooks from WooCommerce.
        
        Args:
            wcapi: WooCommerce API client
            
        Returns:
            List of webhooks
        """
        try:
            logger.info("Fetching webhooks from WooCommerce")
            
            response = wc_request(
                "GET",
                "webhooks",
                params={"per_page": 100},
                wcapi=wcapi
            )
            
            if response:
                logger.info(f"Found {len(response)} webhooks in WooCommerce")
                return [WooCommerceWebhook(**webhook) for webhook in response]
            else:
                logger.warning("No webhooks found in WooCommerce")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching webhooks from WooCommerce: {e}")
            return []
    
    def test_webhook_delivery(
        self,
        delivery_url: str,
        test_payload: Optional[Dict[str, Any]] = None
    ) -> WebhookTestResult:
        """
        Test webhook delivery by sending a test payload.
        
        Args:
            delivery_url: Webhook delivery URL
            test_payload: Optional test payload
            
        Returns:
            Test result with status and timing
        """
        result = WebhookTestResult(
            success=False,
            message="Not tested"
        )
        
        try:
            if not test_payload:
                test_payload = {
                    "test": True,
                    "message": "Webhook test from WooCommerce-Odoo sync",
                    "timestamp": time.time()
                }
            
            logger.info(f"Testing webhook delivery to {delivery_url}")
            start_time = time.time()
            
            response = requests.post(
                delivery_url,
                json=test_payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            
            response_time = (time.time() - start_time) * 1000  # Convert to ms
            
            result.status_code = response.status_code
            result.response_time_ms = round(response_time, 2)
            
            if 200 <= response.status_code < 300:
                result.success = True
                result.message = f"Webhook delivered successfully ({response.status_code})"
            else:
                result.message = f"Webhook delivery failed with status {response.status_code}"
                result.error_details = response.text[:500]
            
            logger.info(f"Webhook test result: {result.message}, {result.response_time_ms}ms")
            
        except requests.exceptions.Timeout:
            result.message = "Webhook delivery timed out (>10s)"
            result.error_details = "Request timeout"
            logger.error(f"Webhook test timeout: {delivery_url}")
            
        except requests.exceptions.ConnectionError as e:
            result.message = "Could not connect to webhook URL"
            result.error_details = str(e)
            logger.error(f"Webhook test connection error: {e}")
            
        except Exception as e:
            result.message = f"Webhook test error: {str(e)}"
            result.error_details = str(e)
            logger.error(f"Webhook test error: {e}")
        
        return result
    
    def sync_webhook_to_woocommerce(
        self,
        webhook_id: int,
        wcapi: API
    ) -> WebhookSyncResult:
        """
        Synchronize a webhook configuration to WooCommerce.
        Creates webhook in WooCommerce if it doesn't exist.
        
        Args:
            webhook_id: Local webhook configuration ID
            wcapi: WooCommerce API client
            
        Returns:
            Sync result with status
        """
        result = WebhookSyncResult(
            webhook_id=webhook_id,
            wc_webhook_id=None,
            success=False,
            message="Not synced"
        )
        
        try:
            webhook = self.webhook_repo.get_by_id(webhook_id)
            if not webhook:
                result.message = f"Webhook {webhook_id} not found"
                return result
            
            if webhook.wc_webhook_id:
                # Update existing webhook in WooCommerce
                update_data = {
                    "topic": webhook.topic,
                    "delivery_url": webhook.delivery_url,
                    "secret": webhook.secret or "",
                    "status": webhook.status,
                    "name": webhook.name or f"Webhook {webhook.topic}"
                }
                
                wc_response = self.update_webhook_in_woocommerce(
                    wcapi,
                    webhook.wc_webhook_id,
                    update_data
                )
                
                if wc_response:
                    result.success = True
                    result.wc_webhook_id = webhook.wc_webhook_id
                    result.message = f"Updated webhook {webhook.wc_webhook_id} in WooCommerce"
                else:
                    result.message = "Failed to update webhook in WooCommerce"
                    
            else:
                # Create new webhook in WooCommerce
                webhook_data = WebhookConfigCreate(
                    instance_id=webhook.instance_id,
                    topic=webhook.topic,
                    delivery_url=webhook.delivery_url,
                    name=webhook.name,
                    secret=webhook.secret,
                    status=webhook.status,
                    active=webhook.active
                )
                
                wc_response = self.create_webhook_in_woocommerce(wcapi, webhook_data)
                
                if wc_response:
                    # Update local webhook with WC webhook ID
                    self.webhook_repo.update_wc_webhook_id(
                        webhook_id,
                        wc_response.get('id')
                    )
                    
                    result.success = True
                    result.wc_webhook_id = wc_response.get('id')
                    result.message = f"Created webhook {result.wc_webhook_id} in WooCommerce"
                else:
                    result.message = "Failed to create webhook in WooCommerce"
            
        except Exception as e:
            result.message = f"Error syncing webhook: {str(e)}"
            result.error_details = str(e)
            logger.error(f"Error syncing webhook {webhook_id}: {e}")
        
        return result
