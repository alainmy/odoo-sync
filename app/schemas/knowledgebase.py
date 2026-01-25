from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


# ------------------ USERS ------------------
class UserBase(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    email: Optional[str] = None


class UserCreate(UserBase):
    pass


class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


# ------------------ PROJECTS ------------------
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class Project(ProjectBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


# ------------------ DOCUMENTS ------------------
class DocumentBase(BaseModel):
    project_id: int
    title: str


class DocumentCreate(DocumentBase):
    pass


class Document(DocumentBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


# ------------------ DOCUMENT CHUNKS ------------------
class DocumentChunkBase(BaseModel):
    document_id: int
    chunk_index: int
    content: str
    embedding: List[float]  # vector como lista de floats


class DocumentChunkCreate(DocumentChunkBase):
    pass


class DocumentChunk(DocumentChunkBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
