from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from decimal import Decimal

class OdooProduct(BaseModel):
    """Modelo para productos que vienen desde Odoo"""
    
    # Campos básicos
    id: Optional[int] = None  # ID en Odoo
    name: str
    default_code: Optional[str] = Field(None, description="SKU del producto")  # SKU en Odoo
    
    # Precios
    list_price: Optional[Decimal] = Field(None, description="Precio de venta")
    standard_price: Optional[Decimal] = Field(None, description="Costo del producto")
    
    # Descripción y categoría
    description: Optional[str] = None
    description_sale: Optional[str] = None
    categ_id: Optional[int] = None
    categ_name: Optional[str] = None
    
    # Estado y tipo
    active: bool = True
    sale_ok: bool = True
    purchase_ok: bool = True
    type: str = Field(default="product", description="consu, service, product")
    
    # Inventario
    qty_available: Optional[Decimal] = Field(None, description="Cantidad disponible")
    virtual_available: Optional[Decimal] = Field(None, description="Cantidad virtual")
    
    # Atributos adicionales
    weight: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    
    # Imágenes (URLs)
    image_urls: Optional[List[str]] = Field(default_factory=list)
    
    # Metadatos
    create_date: Optional[str] = None
    write_date: Optional[str] = None


class OdooToWooCommerceRequest(BaseModel):
    """Request para sincronizar productos de Odoo a WooCommerce"""
    products: List[OdooProduct]
    create_if_not_exists: bool = Field(default=True, description="Crear producto si no existe")
    update_existing: bool = Field(default=True, description="Actualizar si ya existe")
    sync_images: bool = Field(default=False, description="Sincronizar imágenes")
    default_status: str = Field(default="publish", description="Estado por defecto: draft, pending, private, publish")


class ProductSyncResult(BaseModel):
    """Resultado de sincronización de un producto"""
    odoo_id: Optional[int] = None
    odoo_sku: Optional[str] = None
    woocommerce_id: Optional[int] = None
    action: str  # created, updated, skipped, error
    success: bool
    message: str
    error_details: Optional[str] = None

class OdooToWooCommerceSyncResponse(BaseModel):
    """Respuesta completa de sincronización"""
    total_products: int
    successful: int
    failed: int
    created: int
    updated: int
    skipped: int
    results: List[ProductSyncResult]
    sync_duration_seconds: Optional[float] = None

class WooCommerceProductCreate(BaseModel):
    """Modelo para crear/actualizar productos en WooCommerce"""
    name: str
    type: str = "simple"  # simple, grouped, external, variable
    regular_price: Optional[str] = None
    sale_price: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    sku: Optional[str] = None
    manage_stock: bool = False
    stock_quantity: Optional[int] = None
    in_stock: bool = True
    status: str = "publish"  # draft, pending, private, publish
    categories: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, str]]] = None
    weight: Optional[str] = None
    dimensions: Optional[Dict[str, str]] = None
    
    class Config:
        # Permitir campos adicionales para flexibilidad
        extra = "allow"


class OdooCategory(BaseModel):
    """Modelo para categorías de productos que vienen desde Odoo"""
    
    # Campos básicos
    id: int  # ID en Odoo
    name: str
    complete_name: Optional[str] = Field(None, description="Nombre completo con jerarquía")
    
    # Jerarquía
    parent_id: Optional[int] = Field(None, description="ID de la categoría padre en Odoo")
    parent_name: Optional[str] = Field(None, description="Nombre de la categoría padre")
    
    # Descripción
    description: Optional[str] = None
    
    # Metadatos
    create_date: Optional[str] = None
    write_date: Optional[str] = None


class CategorySyncResult(BaseModel):
    """Resultado de sincronización de una categoría"""
    odoo_id: int
    odoo_name: str
    woocommerce_id: Optional[int] = None
    action: str  # created, updated, skipped, error
    success: bool
    message: str
    error_details: Optional[str] = None


class OdooCategoriesToWooCommerceRequest(BaseModel):
    """Request para sincronizar categorías de Odoo a WooCommerce"""
    categories: List[OdooCategory]
    create_if_not_exists: bool = Field(default=True, description="Crear categoría si no existe")
    update_existing: bool = Field(default=True, description="Actualizar si ya existe")
    create_hierarchy: bool = Field(default=True, description="Crear jerarquía de categorías padre-hijo")


class OdooCategoriesToWooCommerceSyncResponse(BaseModel):
    """Respuesta completa de sincronización de categorías"""
    total_categories: int
    successful: int
    failed: int
    created: int
    updated: int
    skipped: int
    results: List[CategorySyncResult]
    sync_duration_seconds: Optional[float] = None


class WooCommerceCategoryCreate(BaseModel):
    """Modelo para crear/actualizar categorías en WooCommerce"""
    name: str
    slug: Optional[str] = None
    parent: Optional[int] = Field(None, description="ID de la categoría padre en WooCommerce")
    description: Optional[str] = None
    display: str = Field(default="default", description="default, products, subcategories, both")
    image: Optional[Dict[str, str]] = None
    menu_order: int = Field(default=0)
    
    class Config:
        extra = "allow"