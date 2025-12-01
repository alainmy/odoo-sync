from typing import Any, Optional
from pydantic import BaseModel


class ProductBase(BaseModel):

    id: int
    name: str
    description: Optional[str] = None
    price: float
    image: Optional[str] = None
    categ_id: Optional[list] = None
    sale_ok: bool
    uom_id: Optional[list] = None
    uom_po_id: Optional[list] = None
    uom_category_id: Optional[list] = None
    weight: float
    weight_uom_name: str
    volume: float
    volume_uom_name: str

    @classmethod
    def from_odoo(cls, odoo_product):
        return cls(
            id=odoo_product["id"],
            name=odoo_product["name"],
            description=odoo_product["description"] or None,
            price=odoo_product["list_price"],
            image=odoo_product["image_1920"] or None,
            categ_id=odoo_product["categ_id"],
            sale_ok=odoo_product["sale_ok"],
            uom_id=odoo_product["uom_id"],
            uom_po_id=odoo_product["uom_po_id"],
            uom_category_id=odoo_product["uom_category_id"],
            weight=odoo_product["weight"],
            weight_uom_name=odoo_product["weight_uom_name"],
            volume=odoo_product["volume"],
            volume_uom_name=odoo_product["volume_uom_name"],
        )
