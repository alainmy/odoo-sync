"""Repository for webhook configuration CRUD operations."""

import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.webhook_models import WebhookConfig
from app.schemas.webhook_schemas import WebhookConfigCreate, WebhookConfigUpdate

logger = logging.getLogger(__name__)


class WebhookConfigRepository:
    """Repository for managing webhook configurations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_id(self, webhook_id: int) -> Optional[WebhookConfig]:
        """Get webhook by ID."""
        return self.db.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
    
    def get_all_by_instance(self, instance_id: int) -> List[WebhookConfig]:
        """Get all webhooks for an instance."""
        return self.db.query(WebhookConfig).filter(
            WebhookConfig.instance_id == instance_id
        ).order_by(WebhookConfig.created_at.desc()).all()
    
    def get_active_by_instance(self, instance_id: int) -> List[WebhookConfig]:
        """Get only active webhooks for an instance."""
        return self.db.query(WebhookConfig).filter(
            WebhookConfig.instance_id == instance_id,
            WebhookConfig.active == True
        ).all()
    
    def get_by_topic(self, instance_id: int, topic: str) -> List[WebhookConfig]:
        """Get webhooks by topic for an instance."""
        return self.db.query(WebhookConfig).filter(
            WebhookConfig.instance_id == instance_id,
            WebhookConfig.topic == topic
        ).all()
    
    def get_by_wc_webhook_id(self, wc_webhook_id: int) -> Optional[WebhookConfig]:
        """Get webhook by WooCommerce webhook ID."""
        return self.db.query(WebhookConfig).filter(
            WebhookConfig.wc_webhook_id == wc_webhook_id
        ).first()
    
    def create(self, webhook_data: WebhookConfigCreate) -> Optional[WebhookConfig]:
        """
        Create a new webhook configuration.
        
        Args:
            webhook_data: Webhook configuration data
            
        Returns:
            Created webhook or None if failed
        """
        try:
            webhook = WebhookConfig(**webhook_data.model_dump())
            self.db.add(webhook)
            self.db.commit()
            self.db.refresh(webhook)
            logger.info(f"Created webhook config {webhook.id} for instance {webhook.instance_id}")
            return webhook
        except Exception as e:
            logger.error(f"Error creating webhook: {e}")
            self.db.rollback()
            return None
    
    def update(self, webhook_id: int, webhook_data: WebhookConfigUpdate) -> Optional[WebhookConfig]:
        """
        Update a webhook configuration.
        
        Args:
            webhook_id: Webhook ID
            webhook_data: Updated webhook data
            
        Returns:
            Updated webhook or None if not found
        """
        try:
            webhook = self.get_by_id(webhook_id)
            if not webhook:
                return None
            
            update_dict = webhook_data.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                setattr(webhook, key, value)
            
            self.db.commit()
            self.db.refresh(webhook)
            logger.info(f"Updated webhook {webhook_id}")
            return webhook
        except Exception as e:
            logger.error(f"Error updating webhook {webhook_id}: {e}")
            self.db.rollback()
            return None
    
    def update_wc_webhook_id(self, webhook_id: int, wc_webhook_id: int) -> Optional[WebhookConfig]:
        """Update WooCommerce webhook ID."""
        try:
            webhook = self.get_by_id(webhook_id)
            if not webhook:
                return None
            
            webhook.wc_webhook_id = wc_webhook_id
            self.db.commit()
            self.db.refresh(webhook)
            logger.info(f"Updated webhook {webhook_id} with WC webhook ID {wc_webhook_id}")
            return webhook
        except Exception as e:
            logger.error(f"Error updating WC webhook ID for {webhook_id}: {e}")
            self.db.rollback()
            return None
    
    def update_delivery_metrics(self, webhook_id: int) -> Optional[WebhookConfig]:
        """Increment delivery count and update last delivery time."""
        try:
            webhook = self.get_by_id(webhook_id)
            if not webhook:
                return None
            
            webhook.delivery_count += 1
            webhook.last_delivery_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(webhook)
            return webhook
        except Exception as e:
            logger.error(f"Error updating delivery metrics for {webhook_id}: {e}")
            self.db.rollback()
            return None
    
    def delete(self, webhook_id: int) -> bool:
        """
        Delete a webhook configuration.
        
        Args:
            webhook_id: Webhook ID
            
        Returns:
            True if deleted, False if not found
        """
        try:
            webhook = self.get_by_id(webhook_id)
            if not webhook:
                return False
            
            self.db.delete(webhook)
            self.db.commit()
            logger.info(f"Deleted webhook {webhook_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting webhook {webhook_id}: {e}")
            self.db.rollback()
            return False
