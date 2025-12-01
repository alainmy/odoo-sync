from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.crud.admin import *
from app.schemas.admin import *
from app.db.session import get_db

router = APIRouter()

@router.post("/", response_model=Admin)
def create_admin(item: AdminCreate, db: Session = Depends(get_db)):
    return create_admin(db=db, item=item)

@router.get("/{item_id}", response_model=Admin)
def read_admin(item_id: int, db: Session = Depends(get_db)):
    db_item = get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return db_item

@router.put("/{item_id}", response_model=Admin)
def update_admin(item_id: int, item: AdminCreate, db: Session = Depends(get_db)):
    db_item = get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return update_admin(db=db, db_item=db_item, item=item)

@router.delete("/{item_id}", response_model=Admin)
def delete_admin(item_id: int, db: Session = Depends(get_db)):
    db_item = get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return delete_admin(db=db, item_id=item_id)

# Add more routes as needed
