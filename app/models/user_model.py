from sqlalchemy import Column, ForeignKey, Integer, String, Boolean
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True)
    email = Column(String(255), unique=True, index=True)
    full_name = Column(String(255), index=True)
    hashed_password = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)


class ClientSync(Base):
    __tablename__ = "client_sync"

    id = Column(Integer, primary_key=True, index=True)
    odoo_id = Column(Integer, nullable=False)
    woo_id = Column(Integer, nullable=False)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=True)
    last_synced_at = Column(String(255), nullable=True)
    contact_type = Column(String(20), nullable=True)
    parent_id = Column(ForeignKey("client_sync.id"), nullable=True)
    sync_status = Column(String(20), nullable=True)