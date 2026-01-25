from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.crud import admin as crud_admin
from app.schemas.admin import Admin as AdminSchema, AdminCreate
from app.db.session import get_db
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin as AdminModel

router = APIRouter()

# Endpoint para obtener información del usuario actual
# DEBE ir ANTES de /{item_id} para evitar conflictos de rutas
@router.get("/me", response_model=AdminSchema)
def read_current_admin(
    db: Session = Depends(get_db),
    current_user: AdminModel = Depends(get_current_user)
):
    """
    Obtener información del usuario autenticado actual.
    """
    return current_user

# Nota: Este endpoint permite crear admins solo desde scripts/setup inicial
# En producción debería estar deshabilitado o requerir un token especial
@router.post("/", response_model=AdminSchema)
def create_admin(
    item: AdminCreate, 
    db: Session = Depends(get_db),
    current_user: AdminModel = Depends(get_current_user)
):
    """
    Crear un nuevo admin. 
    SOLO para uso administrativo - requiere autenticación.
    """
    # Solo admins pueden crear otros admins
    return crud_admin.create_admin(db=db, item=item)

@router.get("/{item_id}", response_model=AdminSchema)
def read_admin(
    item_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminModel = Depends(get_current_user)
):
    """
    Obtener información de un admin.
    Los usuarios solo pueden ver su propia información.
    """
    # Los usuarios solo pueden ver su propia información
    if current_user.id != item_id:
        raise HTTPException(
            status_code=403, 
            detail="No tiene permisos para ver información de otros usuarios"
        )
    
    db_item = crud_admin.get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return db_item

@router.put("/{item_id}", response_model=AdminSchema)
def update_admin(
    item_id: int, 
    item: AdminCreate, 
    db: Session = Depends(get_db),
    current_user: AdminModel = Depends(get_current_user)
):
    """
    Actualizar un admin.
    Los usuarios solo pueden actualizar su propia información.
    """
    # Los usuarios solo pueden actualizar su propia información
    if current_user.id != item_id:
        raise HTTPException(
            status_code=403, 
            detail="No tiene permisos para modificar otros usuarios"
        )
    
    db_item = crud_admin.get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return crud_admin.update_admin(db=db, db_item=db_item, item=item)

@router.delete("/{item_id}", response_model=AdminSchema)
def delete_admin(
    item_id: int, 
    db: Session = Depends(get_db),
    current_user: AdminModel = Depends(get_current_user)
):
    """
    Eliminar un admin.
    Los usuarios solo pueden eliminar su propia cuenta.
    """
    # Los usuarios solo pueden eliminar su propia cuenta
    if current_user.id != item_id:
        raise HTTPException(
            status_code=403, 
            detail="No tiene permisos para eliminar otros usuarios"
        )
    
    db_item = crud_admin.get_admin(db=db, item_id=item_id)
    if db_item is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    return crud_admin.delete_admin(db=db, item_id=item_id)
