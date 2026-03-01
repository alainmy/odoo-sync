"""Pydantic schemas for webhook management."""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal
from datetime import datetime


# Webhook topics available in WooCommerce
WebhookTopic = Literal[
    "product.created", "product.updated", "product.deleted", "product.restored",
    "order.created", "order.updated", "order.deleted", "order.restored",
    "customer.created", "customer.updated", "customer.deleted",
    "coupon.created", "coupon.updated", "coupon.deleted", "coupon.restored",
    "action.woocommerce_add_to_cart", "action.woocommerce_update_order",
]

WebhookStatus = Literal["active", "paused", "disabled"]


class WebhookConfigBase(BaseModel):
    """Base schema for webhook configuration."""
    instance_id: int = Field(..., description="WooCommerce instance ID")
    topic: WebhookTopic = Field(..., description="Webhook topic/event")
    delivery_url: str = Field(None, description="URL where webhook payload is sent")
    name: Optional[str] = Field(None, description="Friendly name for webhook")
    secret: Optional[str] = Field(None, description="Secret for webhook signature verification")
    status: WebhookStatus = Field(default="active", description="Webhook status")
    active: bool = Field(default=True, description="Is webhook active")


class WebhookConfigCreate(WebhookConfigBase):
    """Schema for creating a new webhook."""
    pass


class WebhookConfigUpdate(BaseModel):
    """Schema for updating a webhook."""
    topic: Optional[WebhookTopic] = None
    delivery_url: Optional[str] = None
    name: Optional[str] = None
    secret: Optional[str] = None
    status: Optional[WebhookStatus] = None
    active: Optional[bool] = None


class WebhookConfigResponse(WebhookConfigBase):
    """Schema for webhook response."""
    id: int
    wc_webhook_id: Optional[int]
    api_version: str
    delivery_count: int
    last_delivery_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class WooCommerceWebhook(BaseModel):
    """Schema for WooCommerce webhook data from API."""
    id: int
    name: str
    status: str
    topic: str
    resource: str
    event: str
    hooks: list
    delivery_url: str
    secret: Optional[str] = None
    date_created: str
    date_created_gmt: str
    date_modified: str
    date_modified_gmt: str


class WebhookTestResult(BaseModel):
    """Schema for webhook test result."""
    success: bool
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    message: str
    error_details: Optional[str] = None


class WebhookSyncResult(BaseModel):
    """Schema for webhook synchronization result."""
    webhook_id: int
    wc_webhook_id: Optional[int]
    success: bool
    message: str
    error_details: Optional[str] = None
