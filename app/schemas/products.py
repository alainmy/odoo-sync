from typing import List, Optional
from pydantic import BaseModel


class OdooProductSchema(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    default_code: Optional[str] = None
    list_price: Optional[float] = None
    standard_price: Optional[float] = None
    description: Optional[str] = None
    description_sale: Optional[str] = None
    categ_id: Optional[int] = None
    categ_name: Optional[str] = None
    active: Optional[bool] = None
    sale_ok: Optional[bool] = None
    purchase_ok: Optional[bool] = None
    type: Optional[str] = None
    qty_available: Optional[float] = None
    virtual_available: Optional[float] = None
    weight: Optional[float] = None
    volume: Optional[float] = None
    image_urls: Optional[List[str]] = None
    create_date: Optional[str] = None
    write_date: Optional[str] = None

    @classmethod
    def from_odoo(cls, odoo_product):
        return cls(
            id=odoo_product["id"] or None,
            name=odoo_product["name"] or None,
            default_code=odoo_product["default_code"] or None,
            list_price=odoo_product["list_price"] or None,
            standard_price=odoo_product["standard_price"] or None,
            description=odoo_product["description"] or None,
            description_sale=odoo_product["description_sale"] or None,
            categ_id=odoo_product["categ_id"][0] or None,
            categ_name=odoo_product["categ_id"][1] or None,
            active=odoo_product["active"] or None,
            sale_ok=odoo_product["sale_ok"] or None,
            purchase_ok=odoo_product["purchase_ok"] or None,
            type=odoo_product["type"] or None,
            qty_available=odoo_product["qty_available"] or None,
            virtual_available=odoo_product["virtual_available"] or None,
            weight=odoo_product["weight"] or None,
            volume=odoo_product["volume"] or None,
            image_urls=odoo_product["image_1920"] or None,
            create_date=odoo_product["create_date"] or None,
            write_date=odoo_product["write_date"] or None,
        )

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
