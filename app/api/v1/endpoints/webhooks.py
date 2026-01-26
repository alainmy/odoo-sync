"""API endpoints for webhook management."""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.webhook_schemas import (
    WebhookConfigCreate,
    WebhookConfigUpdate,
    WebhookConfigResponse,
    WebhookTestResult,
    WebhookSyncResult,
    WooCommerceWebhook
)
from app.repositories.webhook_config_repository import WebhookConfigRepository
from app.services.webhook_service import WebhookService
from app.models.admin import WooCommerceInstance
from app.tasks.sync_helpers import create_wc_api_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# WEBHOOK CONFIGURATION ENDPOINTS
# ============================================================================

@router.get("/config", response_model=List[WebhookConfigResponse])
def get_webhook_configs(
    instance_id: int,
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get all webhook configurations for an instance.
    
    Args:
        instance_id: WooCommerce instance ID
        active_only: Return only active webhooks
        db: Database session
    """
    repo = WebhookConfigRepository(db)
    
    if active_only:
        webhooks = repo.get_active_by_instance(instance_id)
    else:
        webhooks = repo.get_all_by_instance(instance_id)
    
    return webhooks


@router.get("/config/{webhook_id}", response_model=WebhookConfigResponse)
def get_webhook_config(
    webhook_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific webhook configuration."""
    repo = WebhookConfigRepository(db)
    webhook = repo.get_by_id(webhook_id)
    
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found"
        )
    
    return webhook


@router.post("/config", response_model=WebhookConfigResponse, status_code=status.HTTP_201_CREATED)
def create_webhook_config(
    config: WebhookConfigCreate,
    create_in_wc: bool = True,
    db: Session = Depends(get_db)
):
    """
    Create a new webhook configuration and optionally create it in WooCommerce.
    
    Args:
        config: Webhook configuration data
        create_in_wc: Also create webhook in WooCommerce (default: True)
        db: Database session
    """
    repo = WebhookConfigRepository(db)
    
    # Validate instance exists
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == config.instance_id
    ).first()
    
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {config.instance_id} not found"
        )
    
    # Create webhook in local database
    new_webhook = repo.create(config)
    if not new_webhook:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create webhook configuration"
        )
    
    # Create webhook in WooCommerce if requested
    if create_in_wc:
        try:
            wc_config = {
                "url": instance.woocommerce_url,
                "consumer_key": instance.woocommerce_consumer_key,
                "consumer_secret": instance.woocommerce_consumer_secret
            }
            wcapi = create_wc_api_client(wc_config)
            service = WebhookService(db)
            
            wc_response = service.create_webhook_in_woocommerce(wcapi, config)
            
            if wc_response and wc_response.get('id'):
                # Update local webhook with WooCommerce ID
                repo.update_wc_webhook_id(new_webhook.id, wc_response.get('id'))
                
                # Refresh to get updated data
                db.refresh(new_webhook)
                logger.info(f"Created webhook in WooCommerce with ID {wc_response.get('id')}")
            else:
                logger.warning(f"Webhook created locally but failed to create in WooCommerce")
                
        except Exception as e:
            logger.error(f"Error creating webhook in WooCommerce: {e}")
            # Don't fail the request, webhook is created locally
    
    return new_webhook


@router.put("/config/{webhook_id}", response_model=WebhookConfigResponse)
def update_webhook_config(
    webhook_id: int,
    update_data: WebhookConfigUpdate,
    update_in_wc: bool = True,
    db: Session = Depends(get_db)
):
    """
    Update a webhook configuration and optionally update it in WooCommerce.
    
    Args:
        webhook_id: Webhook ID
        update_data: Data to update
        update_in_wc: Also update webhook in WooCommerce (default: True)
        db: Database session
    """
    repo = WebhookConfigRepository(db)
    
    # Get webhook before update to check if it exists and has WC ID
    webhook = repo.get_by_id(webhook_id)
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found"
        )
    
    # Update webhook in local database
    updated_webhook = repo.update(webhook_id, update_data)
    if not updated_webhook:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update webhook configuration"
        )
    
    # Update webhook in WooCommerce if requested and it has WC ID
    if update_in_wc and updated_webhook.wc_webhook_id:
        try:
            instance = db.query(WooCommerceInstance).filter(
                WooCommerceInstance.id == updated_webhook.instance_id
            ).first()
            
            if instance:
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret
                }
                wcapi = create_wc_api_client(wc_config)
                service = WebhookService(db)
                
                # Only update status in WooCommerce (topic and delivery_url cannot be changed)
                wc_update_data = {
                    "status": updated_webhook.status
                }
                
                wc_response = service.update_webhook_in_woocommerce(
                    wcapi,
                    updated_webhook.wc_webhook_id,
                    wc_update_data
                )
                
                if wc_response:
                    logger.info(f"Updated webhook {updated_webhook.wc_webhook_id} status in WooCommerce")
                else:
                    logger.warning(f"Webhook updated locally but failed to update in WooCommerce")
                    
        except Exception as e:
            logger.error(f"Error updating webhook in WooCommerce: {e}")
            # Don't fail the request, webhook is updated locally
    
    return updated_webhook


@router.delete("/config/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook_config(
    webhook_id: int,
    delete_from_wc: bool = True,
    db: Session = Depends(get_db)
):
    """
    Delete a webhook configuration.
    
    Args:
        webhook_id: Webhook ID
        delete_from_wc: Also delete from WooCommerce
        db: Database session
    """
    repo = WebhookConfigRepository(db)
    webhook = repo.get_by_id(webhook_id)
    
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found"
        )
    
    # Delete from WooCommerce if requested and webhook has WC ID
    if delete_from_wc and webhook.wc_webhook_id:
        try:
            instance = db.query(WooCommerceInstance).filter(
                WooCommerceInstance.id == webhook.instance_id
            ).first()
            
            if instance:
                wc_config = {
                    "url": instance.woocommerce_url,
                    "consumer_key": instance.woocommerce_consumer_key,
                    "consumer_secret": instance.woocommerce_consumer_secret
                }
                wcapi = create_wc_api_client(wc_config)
                service = WebhookService(db)
                service.delete_webhook_in_woocommerce(wcapi, webhook.wc_webhook_id)
        except Exception as e:
            logger.error(f"Error deleting webhook from WooCommerce: {e}")
            # Continue with local deletion even if WC deletion fails
    
    if not repo.delete(webhook_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete webhook"
        )
    
    return None


# ============================================================================
# WOOCOMMERCE INTEGRATION ENDPOINTS
# ============================================================================

@router.get("/woocommerce/{instance_id}", response_model=List[WooCommerceWebhook])
def get_woocommerce_webhooks(
    instance_id: int,
    db: Session = Depends(get_db)
):
    """
    Get all webhooks from WooCommerce for an instance.
    
    Args:
        instance_id: WooCommerce instance ID
        db: Database session
    """
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id
    ).first()
    
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )
    
    try:
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret
        }
        wcapi = create_wc_api_client(wc_config)
        service = WebhookService(db)
        
        webhooks = service.get_webhooks_from_woocommerce(wcapi)
        return webhooks
        
    except Exception as e:
        logger.error(f"Error fetching webhooks from WooCommerce: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching webhooks: {str(e)}"
        )


@router.post("/sync/{webhook_id}", response_model=WebhookSyncResult)
def sync_webhook_to_woocommerce(
    webhook_id: int,
    db: Session = Depends(get_db)
):
    """
    Synchronize a webhook configuration to WooCommerce.
    Creates or updates the webhook in WooCommerce.
    
    Args:
        webhook_id: Local webhook configuration ID
        db: Database session
    """
    repo = WebhookConfigRepository(db)
    webhook = repo.get_by_id(webhook_id)
    
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found"
        )
    
    try:
        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == webhook.instance_id
        ).first()
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {webhook.instance_id} not found"
            )
        
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret
        }
        wcapi = create_wc_api_client(wc_config)
        service = WebhookService(db)
        
        result = service.sync_webhook_to_woocommerce(webhook_id, wcapi)
        
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.message
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing webhook {webhook_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error syncing webhook: {str(e)}"
        )


@router.post("/test", response_model=WebhookTestResult)
def test_webhook_delivery(
    delivery_url: str,
    db: Session = Depends(get_db)
):
    """
    Test webhook delivery by sending a test payload.
    
    Args:
        delivery_url: Webhook delivery URL to test
        db: Database session
    """
    try:
        service = WebhookService(db)
        result = service.test_webhook_delivery(delivery_url)
        return result
        
    except Exception as e:
        logger.error(f"Error testing webhook delivery: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error testing webhook: {str(e)}"
        )
