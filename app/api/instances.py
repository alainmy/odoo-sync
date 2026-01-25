from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.db.session import get_db
from app.schemas.instance import (
    WooCommerceInstance, 
    WooCommerceInstanceCreate, 
    WooCommerceInstanceUpdate
)
from app.crud import instance as crud_instance
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin

router = APIRouter(
    prefix="/instances",
    tags=["instances"]
)


@router.get("", response_model=List[WooCommerceInstance])
def list_instances(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Listar todas las instancias del usuario actual"""
    instances = crud_instance.get_instances_by_user(db, user_id=current_user.id, skip=skip, limit=limit)
    return instances


@router.get("/active", response_model=WooCommerceInstance)
def get_active_instance(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Obtener la instancia activa del usuario"""
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay ninguna instancia activa"
        )
    return instance


@router.get("/{instance_id}", response_model=WooCommerceInstance)
def get_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Obtener una instancia específica"""
    instance = crud_instance.get_instance(db, instance_id=instance_id, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instancia no encontrada"
        )
    return instance


@router.post("", response_model=WooCommerceInstance, status_code=status.HTTP_201_CREATED)
def create_instance(
    instance: WooCommerceInstanceCreate,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Crear una nueva instancia"""
    return crud_instance.create_instance(db, instance=instance, user_id=current_user.id)


@router.put("/{instance_id}", response_model=WooCommerceInstance)
def update_instance(
    instance_id: int,
    instance_update: WooCommerceInstanceUpdate,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Actualizar una instancia"""
    instance = crud_instance.update_instance(
        db, 
        instance_id=instance_id, 
        user_id=current_user.id, 
        instance_update=instance_update
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instancia no encontrada"
        )
    return instance


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Eliminar una instancia"""
    deleted = crud_instance.delete_instance(db, instance_id=instance_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instancia no encontrada"
        )
    return None


@router.patch("/{instance_id}/activate", response_model=WooCommerceInstance)
def activate_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Activar una instancia (desactiva las demás automáticamente)"""
    instance = crud_instance.activate_instance(db, instance_id=instance_id, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instancia no encontrada"
        )
    return instance
