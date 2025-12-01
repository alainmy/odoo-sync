from pydantic import BaseModel, Field
from typing import Optional, List


class CategoryBase(BaseModel):
    """Schema base para categorías"""
    id: Optional[int] = None
    name: str
    slug: Optional[str] = None
    parent_id: Optional[int] = Field(None, description="ID de la categoría padre en Odoo")
    parent_name: Optional[str] = Field(None, description="Nombre de la categoría padre")
    description: Optional[str] = None
    image: Optional[str] = None
    
    class Config:
        from_attributes = True

    @classmethod
    def from_odoo(cls, odoo_data: dict) -> "CategoryBase":
        """
        Convierte datos de Odoo a CategoryBase
        
        Args:
            odoo_data: Diccionario con datos de product.category de Odoo
        
        Returns:
            CategoryBase: Instancia del schema con datos mapeados
        """
        # Procesar parent_id que viene como [id, name] desde Odoo
        parent_id = None
        parent_name = None
        if odoo_data.get("parent_id"):
            if isinstance(odoo_data["parent_id"], list) and len(odoo_data["parent_id"]) > 0:
                parent_id = odoo_data["parent_id"][0]
                parent_name = odoo_data["parent_id"][1] if len(odoo_data["parent_id"]) > 1 else None
            elif isinstance(odoo_data["parent_id"], int):
                parent_id = odoo_data["parent_id"]
        
        return cls(
            id=odoo_data.get("id"),
            name=odoo_data.get("name", ""),
            slug=odoo_data.get("name", "").lower().replace(" ", "-") if odoo_data.get("name") else None,
            parent_id=parent_id,
            parent_name=parent_name,
            description=odoo_data.get("display_name") or odoo_data.get("complete_name"),
            image=None  # Odoo product.category no tiene imagen por defecto
        )


class CategorySyncRequest(BaseModel):
    """Request para sincronizar categorías específicas"""
    category_ids: Optional[List[int]] = Field(None, description="IDs específicos de categorías a sincronizar")
    limit: int = Field(100, ge=1, le=500, description="Límite de categorías a sincronizar")
    offset: int = Field(0, ge=0, description="Offset para paginación")


class CategorySyncResponse(BaseModel):
    """Response de sincronización de categorías"""
    status: str
    message: str
    categories_processed: int
    categories_created: int
    categories_updated: int
    categories_failed: int
    odoo_categories: List[CategoryBase]
    errors: Optional[List[dict]] = None
