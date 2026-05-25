
from typing import List, Optional

from pydantic import BaseModel


class OdooJournal(BaseModel):
    id: int
    name: str
    code: str
    type: str
    active: bool

    class Config:
        orm_mode = True

class OdooJournalListResponse(BaseModel):
    payment_journals: Optional[List[OdooJournal]] = []
    total_count: int