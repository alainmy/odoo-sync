"""
Models para sincronización de Atributos Odoo ↔ WooCommerce

IMPORTANTE: Los atributos y valores ya existen en Odoo (product.attribute, product.attribute.value).
Este módulo solo guarda el MAPEO de sincronización entre Odoo y WooCommerce.

Flujo:
1. Leer atributos de Odoo vía XML-RPC
2. Crear/actualizar en WooCommerce vía REST API
3. Guardar mapeo en AttributeSync y AttributeValueSync
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class AttributeSync(Base):
    """
    Mapeo de sincronización: Odoo product.attribute ↔ WooCommerce products/attributes
    
    Ejemplo:
    - odoo_attribute_id: 5 (Color en Odoo)
    - woocommerce_id: 2 (Color en WooCommerce)
    - instance_id: 1
    """
    __tablename__ = "attribute_syncs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Relación con instancia WooCommerce
    instance_id = Column(Integer, ForeignKey('woocommerce_instances.id'), nullable=False)
    
    # IDs de sincronización
    odoo_attribute_id = Column(Integer, nullable=False, index=True)  # ID en Odoo (product.attribute)
    odoo_name = Column(String(255), index=True, nullable=True)  # Nombre del atributo en Odoo
    woocommerce_id = Column(Integer, nullable=True, index=True)  # ID en WooCommerce API
    
    # Metadatos de WooCommerce
    slug = Column(String(255), nullable=True)
    woo_type = Column(String(50), default='select')  # Siempre 'select' para WooCommerce
    
    # Estado de sincronización
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Control de sincronización
    need_update = Column(Boolean, default=False)
    is_mapped = Column(Boolean, default=False)  # Mapeo manual
    
    # Relaciones
    instance = relationship("WooCommerceInstance")
    
    # Timestamps
    sync_date = Column(DateTime, nullable=True)  # Última modificación
    last_exported_date = Column(DateTime, nullable=True)  # Última exportación exitosa
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AttributeValueSync(Base):
    """
    Mapeo de sincronización: Odoo product.attribute.value ↔ WooCommerce attribute terms
    
    Ejemplo:
    - odoo_value_id: 23 (Rojo en Odoo)
    - woocommerce_id: 45 (Red term en WooCommerce)
    - woocommerce_attribute_id: 2 (Color attribute en WooCommerce)
    - instance_id: 1
    """
    __tablename__ = "attribute_value_syncs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Relación con instancia WooCommerce
    instance_id = Column(Integer, ForeignKey('woocommerce_instances.id'), nullable=False)
    
    # IDs de sincronización
    odoo_value_id = Column(Integer, nullable=False, index=True)  # ID en Odoo (product.attribute.value)
    odoo_name = Column(String(255), index=True, nullable=True)  # Nombre del valor en Odoo
    woocommerce_id = Column(Integer, nullable=True, index=True)  # Term ID en WooCommerce
    woocommerce_attribute_id = Column(Integer, nullable=True)  # Parent Attribute ID en WooCommerce
    
    # Metadatos de WooCommerce
    slug = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    
    # Estado de sincronización
    created = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    skipped = Column(Boolean, default=False)
    error = Column(Boolean, default=False)
    message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Control de sincronización
    need_update = Column(Boolean, default=False)
    
    # Relaciones
    instance = relationship("WooCommerceInstance")
    
    # Timestamps
    sync_date = Column(DateTime, nullable=True)
    last_exported_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
