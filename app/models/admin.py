from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    description = Column(String(500), index=True)


class CategorySync(Base):
    __tablename__ = "category_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    odoo_name = Column(String(255), index=True, nullable=True)
    woocommerce_id = Column(Integer, index=True)

    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id"), nullable=True, index=True)

    # Status flags
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    needs_sync = Column(Boolean, default=False)

    # Messages
    message = Column(String(500), index=True)
    error_details = Column(String(500), index=True)

    # Timestamps
    wc_date_created = Column(DateTime(timezone=True), nullable=True)
    wc_date_updated = Column(DateTime(timezone=True), nullable=True)
    odoo_write_date = Column(DateTime(timezone=True), nullable=True)
    sync_date = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TagSync(Base):
    __tablename__ = "tag_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    odoo_name = Column(String(255), index=True, nullable=True)
    woocommerce_id = Column(Integer, index=True)

    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id"), nullable=True, index=True)

    # Status flags
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    needs_sync = Column(Boolean, default=False)

    # Messages
    message = Column(String(500), index=True)
    error_details = Column(String(500), index=True)

    # Timestamps
    wc_date_created = Column(DateTime(timezone=True), nullable=True)
    wc_date_updated = Column(DateTime(timezone=True), nullable=True)
    odoo_write_date = Column(DateTime(timezone=True), nullable=True)
    sync_date = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ProductSync(Base):
    __tablename__ = "product_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    woocommerce_id = Column(Integer, index=True)

    odoo_name = Column(String(255), index=True)
    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id"), nullable=True, index=True)

    # Status flags
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    published = Column(Boolean, default=False)  # WooCommerce publish status
    needs_sync = Column(Boolean, default=False)  # Pending sync flag

    # Messages
    message = Column(String(500), index=True)
    error_details = Column(String(500), index=True)

    # Timestamps - inspired by ks.woo.product.template
    wc_date_created = Column(DateTime(timezone=True),
                             nullable=True)  # WC creation date
    wc_date_updated = Column(DateTime(timezone=True),
                             nullable=True)  # WC update date
    odoo_write_date = Column(DateTime(timezone=True),
                             nullable=True)  # Odoo last modification
    # Last modification date
    sync_date = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True),
                            nullable=True)  # Last successful sync

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WebhookLog(Base):
    """
    Store webhook events for idempotency and audit trail.
    """
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    # WooCommerce webhook ID
    event_id = Column(String(255), unique=True, index=True)
    # e.g., "product.created", "order.created"
    event_type = Column(String(100), index=True)

    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id"), nullable=True, index=True)

    # SHA256 hash of payload for deduplication
    payload_hash = Column(String(64), index=True)
    payload = Column(JSON)  # Full webhook payload
    # pending, processing, completed, failed
    status = Column(String(50), default="pending")
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CeleryTaskLog(Base):
    """
    Store Celery task execution logs for monitoring and debugging.
    """
    __tablename__ = "celery_task_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(255), unique=True, index=True)
    parent_task_id = Column(String(255), index=True, nullable=True)
    task_name = Column(String(255), index=True)

    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id"), nullable=True, index=True)

    task_args = Column(JSON)
    task_kwargs = Column(JSON)
    # pending, started, retry, success, failure
    status = Column(String(50), default="pending")
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class WooCommerceInstance(Base):
    """
    Store multiple WooCommerce instance configurations.
    """
    __tablename__ = "woocommerce_instances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True)

    # Relación con usuario creador
    user_id = Column(Integer, ForeignKey("users.id"),
                     nullable=False, index=True)

    # WooCommerce connection settings
    woocommerce_url = Column(String(500))
    woocommerce_consumer_key = Column(String(255))
    woocommerce_consumer_secret = Column(String(255))
    webhook_secret = Column(String(255))
    is_active = Column(Boolean, default=True)

    # Odoo connection settings
    odoo_url = Column(String(500))
    odoo_db = Column(String(255))
    odoo_username = Column(String(255))
    odoo_password = Column(String(255))

    # Sync settings
    auto_sync_products = Column(Boolean, default=False)
    auto_sync_orders = Column(Boolean, default=False)
    auto_sync_customers = Column(Boolean, default=False)
    sync_interval_minutes = Column(Integer, default=15)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    webhooks = relationship(
        "WebhookConfig", back_populates="instance", cascade="all, delete-orphan")

    # Odoo language setting
    odoo_language = Column(String(10), default="en_US")

    product_descriptions = Column(String(20), default="product_description")
