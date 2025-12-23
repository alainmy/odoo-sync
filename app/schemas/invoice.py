

from typing import List, Optional

from pydantic import BaseModel


class OdooInvoiceSchema(BaseModel):
    
    invoice_reference: Optional[str] = None
    client_email: Optional[dict] = None
    invoice_date: Optional[str] = None
    invoice_date_due: Optional[str] = None
    # state: Optional[str] = None
    # move_type: Optional[str] = None
    
    line_ids: Optional[List[dict]] = None