from sqlalchemy import Boolean, Column, Integer, String
from app.db.base import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, index=True)


class CategroySync(Base):
    __tablename__ = "category_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    woocommerce_id = Column(Integer, index=True)
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    message = Column(String, index=True)
    error_details = Column(String, index=True)


class ProductSync(Base):
    __tablename__ = "product_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, index=True)
    woocommerce_id = Column(Integer, index=True)
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    message = Column(String, index=True)
    error_details = Column(String, index=True)