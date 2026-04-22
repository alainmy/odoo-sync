
from typing import List, Optional

from pydantic import BaseModel


class OodooConfig(BaseModel):
    url: str
    db: str
    username: str
    password: str


class Website(BaseModel):
    id: int
    name: str


class WebsiteListResponse(BaseModel):
    total: Optional[int] = None
    websites: Optional[List[Website]] = None


class WebsiteResponse(BaseModel):
    website: Website
