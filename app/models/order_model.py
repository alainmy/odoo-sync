
from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, DateTime, func
from app.db.base import Base


class OrderSync(Base):
    __tablename__ = "order_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, nullable=False)
    woo_id = Column(Integer, nullable=False)
    # pending, processing, on-hold, completed, cancelled, refunded, failed and trash
    woo_status = Column(String(50), nullable=False, default="pending")
    odoo_status = Column(String(50), nullable=False)
    # pending, in_progress, completed, failed
    sync_status = Column(String(50), nullable=False, default="pending")
    error_message = Column(String(255), nullable=True)
    sync_date = Column(DateTime(timezone=True), nullable=True)
    instance_id = Column(Integer,
                         ForeignKey('woocommerce_instances.id'),
                         onupdate="CASCADE",
                         nullable=False, index=True)
    # Messages
    message = Column(String(500), index=True)
    error_details = Column(String(500), index=True)

    # Timestamps
    wc_date_created = Column(DateTime(timezone=True),
                             nullable=True)  # WC creation date
    wc_date_updated = Column(DateTime(timezone=True),
                             nullable=True)  # WC update date
    odoo_write_date = Column(DateTime(timezone=True),
                             nullable=True)  # Odoo last modification

    last_synced_at = Column(DateTime(timezone=True),
                            nullable=True)  # Last successful sync

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    customer_sync_id = Column(Integer, nullable=True)

    customer = Column(Integer, ForeignKey("customer_sync.id"), nullable=True)
