"""API endpoints for receiving WooCommerce webhooks."""

import logging
from operator import is_
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, Header, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.admin import ProductSync, WooCommerceInstance
from app.services.webhook_processor import WebhookProcessor
from app.tasks.webhook_tasks import process_webhook
from app.services.woocommerce.client import wc_request_with_logging
from app.tasks.sync_helpers import create_wc_api_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/wc/{instance_id}/{topic}")
async def receive_woocommerce_webhook(
    instance_id: int,
    topic: str,
    request: Request,
    x_wc_webhook_signature: str = Header(None, alias="X-WC-Webhook-Signature"),
    x_wc_webhook_id: str = Header(None, alias="X-WC-Webhook-ID"),
    x_wc_webhook_delivery_id: str = Header(
        None, alias="X-WC-Webhook-Delivery-ID"),
    x_wc_webhook_topic: str = Header(None, alias="X-WC-Webhook-Topic"),
    x_wc_webhook_resource: str = Header(None, alias="X-WC-Webhook-Resource"),
    x_wc_webhook_event: str = Header(None, alias="X-WC-Webhook-Event"),
    x_wc_webhook_source: str = Header(None, alias="X-WC-Webhook-Source"),
    db: Session = Depends(get_db)
):
    """
    Receive webhook from WooCommerce.

    Args:
        instance_id: WooCommerce instance ID
        topic: Webhook topic (e.g., product.created)
        request: FastAPI request object
        x_wc_webhook_signature: Webhook signature for validation
        x_wc_webhook_id: Webhook ID from WooCommerce
        x_wc_webhook_delivery_id: Unique delivery ID
        x_wc_webhook_topic: Webhook topic
        x_wc_webhook_resource: Resource type (product, order, etc.)
        x_wc_webhook_event: Event type (created, updated, deleted)
        x_wc_webhook_source: Source URL of the webhook
        db: Database session

    Returns:
        Acknowledgment response
    """
    try:
        # Collect all webhook headers for logging
        webhook_headers = {
            "user_agent": request.headers.get("user-agent", ""),
            "content_type": request.headers.get("content-type", ""),
            "x_wc_webhook_source": x_wc_webhook_source or "",
            "x_wc_webhook_topic": x_wc_webhook_topic or topic,
            "x_wc_webhook_resource": x_wc_webhook_resource or "",
            "x_wc_webhook_event": x_wc_webhook_event or "",
            "x_wc_webhook_signature": x_wc_webhook_signature or "",
            "x_wc_webhook_id": x_wc_webhook_id or "",
            "x_wc_webhook_delivery_id": x_wc_webhook_delivery_id or ""
        }

        # Get instance configuration
        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()

        if not instance:
            logger.error(f"Instance {instance_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {instance_id} not found"
            )

        if not instance.is_active:
            logger.warning(f"Instance {instance_id} is not active")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Instance is not active"
            )

        # Read raw body for signature validation
        raw_body = await request.body()

        # Parse JSON payload from raw body
        try:
            import json
            payload = json.loads(raw_body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Check if this is a WooCommerce verification ping (form-urlencoded: webhook_id=X)
            body_str = raw_body.decode('utf-8', errors='ignore')
            if body_str.startswith('webhook_id='):
                logger.info(
                    f"Received webhook verification ping for instance {instance_id}, "
                    f"topic {topic}, body: {body_str}"
                )
                return {
                    "status": "ok",
                    "message": "Webhook endpoint verified (ping received)",
                    "webhook_id": x_wc_webhook_id,
                    "event_type": topic
                }

            # Not a ping, invalid JSON
            logger.error(f"Invalid JSON payload: {e}")
            logger.error(f"Raw body (first 500 chars): {raw_body[:500]}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )

        # Log webhook details
        logger.info("=== WEBHOOK RECEIVED ===")
        logger.info(
            f"Instance: {instance_id} ({instance.name}), "
            f"Topic: {webhook_headers['x_wc_webhook_topic']}, "
            f"Event: {webhook_headers['x_wc_webhook_event']}"
        )
        logger.info(
            f"Resource ID: {payload.get('id')}, Delivery ID: {x_wc_webhook_delivery_id}")
        logger.info(f"Source: {webhook_headers['x_wc_webhook_source']}")

        # Initialize processor
        processor = WebhookProcessor(db)

        # Validate signature if secret is configured
        if instance.webhook_secret and x_wc_webhook_signature:
            is_valid = processor.validate_webhook_signature(
                raw_body,
                x_wc_webhook_signature,
                instance.webhook_secret
            )

            if not is_valid:
                logger.error(
                    f"Invalid webhook signature for instance {instance_id}, "
                    f"delivery {x_wc_webhook_delivery_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature"
                )

            logger.info("Webhook signature validated successfully")
        # elif not instance.webhook_secret:
        #     logger.warning(f"No webhook secret configured for instance {instance_id}")

        # Check for duplicate events
        event_id = x_wc_webhook_delivery_id or f"{x_wc_webhook_id}_{payload.get('id')}"
        payload_hash = processor.calculate_payload_hash(payload)

        if processor.is_duplicate_event(event_id, payload_hash):
            logger.info(f"Duplicate event {event_id} - returning 200 OK")
            return {
                "status": "ok",
                "message": "Duplicate event - already processed",
                "event_id": event_id
            }

        # Log webhook event
        log_entry = processor.log_webhook_event(
            event_id=event_id,
            event_type=topic,
            instance_id=instance_id,
            payload=payload,
            status="pending"
        )

        logger.info(
            f"Webhook logged with ID {log_entry.id}, queuing for async processing..."
        )

        # Process webhook asynchronously with Celery
        try:
            process_webhook.apply_async(
                kwargs={
                    'event_type': topic,
                    'payload': payload,
                    'instance_id': instance_id,
                    'event_id': event_id
                },
                queue='webhook_queue'
            )

            logger.info(
                f"Webhook queued successfully: {topic} (instance {instance_id}, log {log_entry.id})"
            )

        except Exception as e:
            logger.error(f"Error queuing webhook task: {e}")
            # Process synchronously as fallback
            processor.process_webhook_event(
                event_type=topic,
                instance_id=instance_id,
                payload=payload,
                log_id=log_entry.id
            )

        # Return 200 OK immediately to acknowledge receipt
        return {
            "status": "ok",
            "message": "Webhook received and queued for processing",
            "delivery_id": x_wc_webhook_delivery_id,
            "event_type": topic
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}"
        )


@router.get("/wc/{instance_id}/health")
def webhook_health_check(instance_id: int, db: Session = Depends(get_db)):
    """
    Health check endpoint for webhook receiver.
    WooCommerce may ping this to verify the endpoint is reachable.

    Args:
        instance_id: WooCommerce instance ID
        db: Database session

    Returns:
        Health status
    """
    try:
        instance = db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()

        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {instance_id} not found"
            )

        return {
            "status": "ok",
            "instance_id": instance_id,
            "instance_name": instance.name,
            "is_active": instance.is_active,
            "message": "Webhook receiver is ready"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# odoo webhook processing flow:
@router.post("/odoo/{instance_id}/{topic}")
async def receive_odoo_webhook(
    instance_id: int,
    topic: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Endpoint to receive webhooks from Odoo.

    Args:
        instance_id: WooCommerce instance ID
        topic: Webhook topic (e.g., product.updated)
        request: FastAPI request object
        db: Database session    
    """
    body = await request.json()
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id
    ).first()
    if not instance:
        logger.error(f"Instance {instance_id} not found for Odoo webhook")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )
    if body['delivery_status'] == 'full' \
            and body['invoice_status'] == 'invoiced':
        logger.info(f"Received Odoo webhook for instance {instance_id}, topic {topic}, "
                    f"order {body.get('order_id')} is fully delivered and invoiced. "
                    f"Triggering WooCommerce order update...")
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret,
        }
        # Assuming client_order_ref is like "SO-12345"
        if 'WC-' in body.get('client_order_ref', ''):
            order_id = body.get('client_order_ref').split('-')[-1]
            wcapi = create_wc_api_client(wc_config)
            update_order = wc_request_with_logging(
                "PUT",
                f"orders/{order_id}",
                params={
                    "status": "completed"
                },
                wcapi=wcapi,
            )
            logger.info(f"WooCommerce order update response: {update_order}")
        # Aquí podrías agregar lógica para actualizar el estado del pedido en WooCommerce
        # o realizar otras acciones según el evento recibido.
    # For now, just log the received webhook
    logger.info(
        f"Received Odoo webhook for instance {instance_id}, topic {topic}")
    return {"status": "ok", "message": "Odoo webhook received"}


async def update_wc_product_data(instance: int, request: Request, db: Session = Depends(get_db)):
    """
    Endpoint to receive webhooks from Odoo.

    Args:
        instance_id: WooCommerce instance ID
        topic: Webhook topic (e.g., product.created)
        request: FastAPI request object
        db: Database session

    Returns:
        Acknowledgment response
    """
    try:
        # Collect all webhook headers for logging
        body = await request.json()
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret,
        }
        prodduct_id = body.get('product_id')
        # get product sync record
        product_sync = db.query(ProductSync).filter(
            ProductSync.odoo_id == prodduct_id,
            ProductSync.instance_id == instance.id
        ).first()
        if not product_sync:
            logger.error(f"Product sync record not found for product {prodduct_id}")
            return {"status": "ok", "message": "Product sync record not found"}
        if not product_sync.woocommerce_id:
            # Buscar en WooCommerce
            wcapi = create_wc_api_client(wc_config)
            wc_product = wc_request_with_logging(
                "GET",
                f"products/{product_sync.woocommerce_id}",
                wcapi=wcapi
            )
            if wc_product:
                # Update product in woocommerce
                re = wc_request_with_logging(
                    "PUT",
                    f"products/{product_sync.woocommerce_id}",
                    params={
                        "name": body.get('name'),
                        "publish": "publish" if body.get('is_published') else "draft",
                        "description": body.get('description_sale'),
                        },
                    wcapi=wcapi
                )
                if re:
                    logger.info(f"Product {product_sync.woocommerce_id} updated in WooCommerce")
                else:
                    logger.error(f"Failed to update product {product_sync.woocommerce_id} in WooCommerce")
                    return {"status": "ok", "message": "Failed to update product in WooCommerce"}
            else:
                logger.error(f"Failed to find product {product_sync.woocommerce_id} in WooCommerce")
                return {"status": "ok", "message": "Failed to find product in WooCommerce"}
                
        logger.info(
            f"Received webhook for instance {instance.id}")
        return {"status": "ok", "message": "Odoo webhook received"}
    except Exception as e:
        logger.error(f"Error processing Odoo webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/odoo/action/{instance_id}/{topic}")
async def receive_odoo_webhook(
    instance_id: int,
    topic: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Endpoint to receive webhooks from Odoo.

    Args:
        instance_id: WooCommerce instance ID
        topic: Webhook topic (e.g., product.updated)
        request: FastAPI request object
        db: Database session    
    """
    body = await request.json()
    instance = db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id
    ).first()
    if not instance:
        logger.error(f"Instance {instance_id} not found for Odoo webhook")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )
    if topic == 'product.update':
        
        update_wc_product_data(instance_id, request, db)
        
    return {"status": "ok", "message": "Odoo webhook received"}
