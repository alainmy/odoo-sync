"""SQLAlchemy models for webhook management."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.base import Base


class WebhookConfig(Base):
    """Model for WooCommerce webhook configurations."""

    __tablename__ = "webhook_config"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("woocommerce_instances.id",
                                             ondelete="CASCADE"), nullable=False)

    # Webhook details
    topic = Column(String(100), nullable=False,
                   comment="e.g., product.created, order.updated")
    delivery_url = Column(String(500), nullable=False,
                          comment="URL where webhook payload is sent")
    secret = Column(String(200), nullable=True,
                    comment="Secret for webhook signature verification")
    name = Column(String(200), nullable=True,
                  comment="Friendly name for webhook")

    # WooCommerce webhook ID
    wc_webhook_id = Column(Integer, nullable=True,
                           comment="WooCommerce webhook ID")

    # Status and configuration
    status = Column(String(20), nullable=False, default="active",
                    comment="active, paused, disabled")
    active = Column(Boolean, nullable=False, default=True)
    api_version = Column(String(10), nullable=False, default="wp_api_v3")

    # Metrics
    delivery_count = Column(Integer, nullable=False, default=0)
    last_delivery_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False,
                        server_default=func.now(), onupdate=func.now())

    # Relationship
    instance = relationship("WooCommerceInstance", back_populates="webhooks")

    def __repr__(self):
        return f"<WebhookConfig(id={self.id}, topic={self.topic}, instance={self.instance_id})>"
