from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class TaxSync(Base):
    __tablename__ = "tax_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    odoo_name = Column(String(255), index=True, nullable=True)
    odoo_description = Column(String(500), nullable=True)
    woocommerce_id = Column(Integer, index=True)

    instance_id = Column(Integer, ForeignKey(
        "woocommerce_instances.id", ondelete="CASCADE"),
        nullable=True, index=True)

    rate = Column(Numeric(10, 4), nullable=True)
    amount = Column(Numeric(10, 4), nullable=True)
    price_include = Column(Boolean, default=False)
    tax_scope = Column(String(50), nullable=True)
    type_tax_use = Column(String(50), nullable=True)
    active = Column(Boolean, default=True)

    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    needs_sync = Column(Boolean, default=False)

    message = Column(String(500), index=True)
    error_details = Column(String(500), index=True)

    wc_date_created = Column(DateTime(timezone=True), nullable=True)
    wc_date_updated = Column(DateTime(timezone=True), nullable=True)
    odoo_write_date = Column(DateTime(timezone=True), nullable=True)
    sync_date = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())