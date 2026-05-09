from sqlalchemy import Boolean, Column, Integer, \
    String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base


class ShippingMethodSync(Base):
    __tablename__ = "shipping_method_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    odoo_name = Column(String(255), index=True, nullable=True)
    woocommerce_id = Column(Integer, index=True)

    # Relación con instancia
    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id", ondelete="CASCADE"),
        nullable=True, index=True)

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