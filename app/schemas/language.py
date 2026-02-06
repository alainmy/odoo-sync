
from typing import Optional
from pydantic import BaseModel

class OdooLanguageSchema(BaseModel):
    """Modelo para idiomas que vienen desde Odoo"""

    id: int  # ID en Odoo
    name: str
    code: str  # Código del idioma, e.g., 'en_US'
    active: bool = True

    # Metadatos
    create_date: Optional[str] = None
    write_date: Optional[str] = None
    
    @classmethod
    def from_odoo(cls, odoo_language):
        return cls(
            id=odoo_language["id"],
            name=odoo_language["name"],
            code=odoo_language["code"],
            active=odoo_language.get("active", True),
        )