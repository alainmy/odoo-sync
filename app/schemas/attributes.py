"""
Schemas Pydantic para Atributos y sincronización Odoo ↔ WooCommerce

IMPORTANTE: Los atributos están en Odoo (product.attribute).
Estos schemas se usan para:
1. Recibir data de Odoo
2. Enviar a WooCommerce
3. Guardar mapeo de sincronización
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Union
from datetime import datetime


# ==================== ODOO ATTRIBUTE SCHEMAS ====================

class OdooAttributeValue(BaseModel):
    """Valor de atributo desde Odoo (product.attribute.value)"""
    id: int = Field(..., description="ID en Odoo")
    name: str = Field(..., description="Nombre del valor (ej: Rojo, S, M)")
    display_name: Optional[str] = Field(None, description="Nombre completo para mostrar")
    html_color: Optional[str] = Field(None, description="Color HTML si es color picker")
    display_type: Optional[str] = Field('radio', description="radio, select, color")
    
    @field_validator('display_name', mode='before')
    @classmethod
    def set_display_name(cls, v, info):
        """Si display_name no viene de Odoo, usar name"""
        if v is None or v is False:
            return info.data.get('name')
        return str(v)
    
    @field_validator('html_color', mode='before')
    @classmethod
    def validate_html_color(cls, v):
        """Odoo puede devolver False en lugar de None para html_color"""
        if v is False or v is None:
            return None
        return str(v)


class OdooAttribute(BaseModel):
    """Atributo desde Odoo (product.attribute)"""
    id: int = Field(..., description="ID en Odoo")
    name: str = Field(..., description="Nombre del atributo (ej: Color, Talla)")
    display_name: Optional[str] = Field(None, description="Nombre completo para mostrar")
    display_type: str = Field(default='radio', description="radio, select, color")
    create_variant: str = Field(default='always', description="always, dynamic, no_variant")
    values: List[OdooAttributeValue] = Field(default=[], description="Valores del atributo")
    
    @field_validator('display_name', mode='before')
    @classmethod
    def set_display_name(cls, v, info):
        """Si display_name no viene de Odoo, usar name"""
        if v is None or v is False:
            return info.data.get('name')
        return str(v)


# ==================== WOOCOMMERCE ATTRIBUTE SCHEMAS ====================

class WooCommerceAttributeTerm(BaseModel):
    """Term (valor) de atributo en WooCommerce"""
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    menu_order: Optional[int] = 0
    count: Optional[int] = 0


class WooCommerceAttribute(BaseModel):
    """Atributo en formato WooCommerce"""
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None
    type: str = Field(default='select', description="Siempre 'select' para WooCommerce")
    order_by: str = Field(default='menu_order', description="menu_order, name, name_num, id")
    has_archives: bool = Field(default=False)


class WooCommerceAttributeCreate(BaseModel):
    """Schema para crear atributo en WooCommerce"""
    name: str
    slug: Optional[str] = None
    type: str = 'select'
    order_by: str = 'menu_order'
    has_archives: bool = False


class WooCommerceAttributeTermCreate(BaseModel):
    """Schema para crear term en WooCommerce"""
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    menu_order: int = 0


# ==================== SYNC REQUEST/RESPONSE SCHEMAS ====================

class AttributeSyncRequest(BaseModel):
    """Request para sincronizar atributos de Odoo a WooCommerce"""
    attributes: List[OdooAttribute] = Field(..., description="Lista de atributos de Odoo")
    create_if_not_exists: bool = Field(default=True, description="Crear si no existe en WooCommerce")
    update_existing: bool = Field(default=True, description="Actualizar si ya existe")
    sync_values: bool = Field(default=True, description="Sincronizar también los valores")


class AttributeSyncResult(BaseModel):
    """Resultado de sincronización de un atributo"""
    odoo_id: int
    odoo_name: str
    woocommerce_id: Optional[int] = None
    success: bool
    action: str = Field(..., description="created, updated, skipped, error")
    message: str
    error_details: Optional[str] = None
    values_synced: int = Field(default=0, description="Cantidad de valores sincronizados")


class AttributeSyncResponse(BaseModel):
    """Respuesta de sincronización de atributos"""
    total_processed: int
    successful: int
    failed: int
    created: int
    updated: int
    skipped: int
    results: List[AttributeSyncResult]
    sync_duration_seconds: float


class AttributeValueSyncResult(BaseModel):
    """Resultado de sincronización de un valor de atributo"""
    odoo_id: int
    odoo_name: str
    woocommerce_id: Optional[int] = None
    success: bool
    action: str = Field(..., description="created, updated, skipped, error")
    message: str
    error_details: Optional[str] = None


class AttributeValueSyncResponse(BaseModel):
    """Respuesta de sincronización de valores de atributos"""
    attribute_id: int
    attribute_name: str
    total_processed: int
    successful: int
    failed: int
    created: int
    updated: int
    skipped: int
    results: List[AttributeValueSyncResult]
    sync_duration_seconds: float


# ==================== ATTRIBUTE SYNC STATUS SCHEMAS ====================

class AttributeSyncStatus(BaseModel):
    """Estado de sincronización de un atributo"""
    id: int
    odoo_attribute_id: int
    odoo_name: Optional[str] = None
    attribute_name: Optional[str] = None
    woocommerce_id: Optional[int] = None
    slug: Optional[str] = None
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: Optional[str] = None
    sync_date: Optional[datetime] = None
    last_exported_date: Optional[datetime] = None
    need_update: bool

    class Config:
        from_attributes = True


class AttributeValueSyncStatus(BaseModel):
    """Estado de sincronización de un valor de atributo"""
    id: int
    odoo_value_id: int
    odoo_name: Optional[str] = None
    value_name: Optional[str] = None
    woocommerce_id: Optional[int] = None
    woocommerce_attribute_id: Optional[int] = None
    slug: Optional[str] = None
    created: bool
    updated: bool
    error: bool
    message: Optional[str] = None
    sync_date: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== ATTRIBUTE MANAGEMENT SCHEMAS ====================

class AttributeSyncStatusResponse(BaseModel):
    """Attribute with sync status for management UI"""
    odoo_id: int
    name: str
    display_name: str
    value_count: int
    values: List[OdooAttributeValue] = []
    sync_status: str  # never_synced, synced, error
    woocommerce_id: Optional[int] = None
    last_synced_at: Optional[datetime] = None
    has_error: bool = False
    error_message: Optional[str] = None


class AttributeListResponse(BaseModel):
    """Response for attribute list"""
    total_count: int
    attributes: List[AttributeSyncStatusResponse]
    filters_applied: dict


class AttributeBatchSyncRequest(BaseModel):
    """Request for batch sync"""
    ids: List[int]


class AttributeBatchSyncResponse(BaseModel):
    """Response for batch sync"""
    total: int
    queued: int
    task_ids: List[str]
    message: str


class AttributeSyncStatsResponse(BaseModel):
    """Attribute sync statistics"""
    total: int
    synced: int
    never_synced: int
    errors: int
