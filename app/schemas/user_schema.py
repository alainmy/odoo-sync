from typing import Optional

from pydantic import BaseModel

class UserBase(BaseModel):
    id: Optional[int] = None
    username: str
    email: str
    full_name: Optional[str] = ''
    changed_password: Optional[str] = None
    is_superuser: Optional[bool] = False

class UserCreate(UserBase):
    password: str
    full_name: Optional[str] = ''
    is_superuser: Optional[bool] = False

class User(UserBase):
    id: int
    full_name: str
    is_active: bool
    is_superuser: bool

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str
    is_superuser: Optional[bool] = False

class TokenData(BaseModel):
    username: str = None
