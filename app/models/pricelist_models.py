"""SQLAlchemy models for pricelist sync."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index, UniqueConstraint
from sqlalchemy.sql import func
from app.db.base import Base
from sqlalchemy.orm import relationship


class PricelistSync(Base):
    """
    Tracks synchronization of Odoo pricelists to WooCommerce.

    Attributes:
        id: Primary key
        odoo_pricelist_id: Odoo pricelist ID
        odoo_pricelist_name: Odoo pricelist name for reference
        instance_id: WooCommerce instance ID
        active: Whether this pricelist is active for sync
        price_type: Type of price (regular, sale, meta)
        meta_key: Meta key for custom price fields (when price_type='meta')
        last_synced_at: Last sync timestamp
        created_at: Record creation timestamp
        updated_at: Record update timestamp
        message: Last sync message or errors
    """

    __tablename__ = "pricelist_sync"

    id = Column(Integer, primary_key=True, autoincrement=True)
    odoo_pricelist_id = Column(
        Integer, nullable=False, comment="Odoo pricelist ID")
    odoo_pricelist_name = Column(
        String(255), nullable=True, comment="Odoo pricelist name")
    instance_id = Column(Integer,
                         nullable=False, comment="WooCommerce instance ID")
    active = Column(Boolean, default=True, nullable=False,
                    comment="Is this pricelist active for sync")
    price_type = Column(String(50), default='regular',
                        nullable=False, comment="Type: regular, sale, meta")
    meta_key = Column(String(100), nullable=True,
                      comment="Meta key for custom price fields")
    last_synced_at = Column(DateTime, nullable=True,
                            comment="Last sync timestamp")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(),
                        onupdate=func.now(), nullable=False)
    message = Column(Text, nullable=True,
                     comment="Last sync message or errors")
    # Assuming a relationship to WooCommerceInstance model
    instances = relationship("WooCommerceInstance",
                             back_populates="price_list")
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('odoo_pricelist_id', 'instance_id',
                         name='uq_pricelist_sync_instance'),
        Index('idx_pricelist_sync_instance', 'instance_id'),
        Index('idx_pricelist_sync_active', 'active'),
    )

    def __repr__(self):
        return f"<PricelistSync(id={self.id}, odoo_pricelist={self.odoo_pricelist_id}, instance={self.instance_id}, type={self.price_type})>"
