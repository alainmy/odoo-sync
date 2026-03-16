

from git import Optional
from pydantic import BaseModel


class OdooClient(BaseModel):

    id: int
    name: str
    complete_name: Optional[str] = None
    email: Optional[str] = None
    last_name: Optional[str] = None
    ref: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    vat: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    country_code: Optional[str] = None
    mobile: Optional[str] = None
    type: Optional[str] = None

    @classmethod
    def from_odoo_data(cls, data: dict) -> "OdooClient":
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            complete_name=data.get("complete_name"),
            email=data.get("email"),
            last_name=data.get("last_name"),
            ref=data.get("ref"),
            phone=data.get("phone"),
            mobile=data.get("mobile"),
            vat=data.get("vat"),
            street=data.get("street"),
            street2=data.get("street2"),
            city=data.get("city"),
            country_code=data.get("country_code"),
            type=data.get("type")
        )


class OdooClientCreate(BaseModel):
    name: str
    complete_name: Optional[str] = None
    email: Optional[str] = None
    last_name: Optional[str] = None
    ref: Optional[str] = None
    phone: Optional[str] = None
    vat: Optional[str] = None
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None
