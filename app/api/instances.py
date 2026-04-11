import os
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
from app.crud.odoo import OdooClient
from app.core.config import settings
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
    instances = crud_instance.get_instances_by_user(
        db, user_id=current_user.id, skip=skip, limit=limit)
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
    instance = crud_instance.get_instance(
        db, instance_id=instance_id, user_id=current_user.id)
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
    try:
        # Obtener propiedasdes del odoo como modulos instalados, version, etc para guardarlas en la instancia
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )
        uid = odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pudo conectar a Odoo con las credenciales proporcionadas"
            )
        odoo_info = odoo_client.get_odoo_info()
        version_info = odoo_info.get("server_version", "Unknown")
        # Get instaled modules
        installed_modules = odoo_client.get_installed_modules()
        modules = [module.get("name") for module in installed_modules if module["name"] in [
            "sale_management", "stock", "account", "product", "website_sale"]]
        installed_modules_names = os.linesep.join(
            [module for module in modules])
        odoo_description = f"Odoo Version {version_info}\n with modules:\n \n{installed_modules_names}"
        instance.odoo_description = odoo_description
        instance_created = crud_instance.create_instance(
            db, instance=instance, user_id=current_user.id)
        # Get or create webhook for update order in WooCommerce
        if 'sale_management' in modules:
            odoo_webhook_url_template = "{host}/api/v1/webhook-receiver/odoo/{instance_id}/order_update"
            webhook = odoo_client.get_webhook_by_url(
                url=odoo_webhook_url_template.format(host=settings.fast_api_host,
                                                    instance_id=instance_created.id))
        """Crear una nueva instancia"""
        return instance_created
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
        )


@router.put("/{instance_id}", response_model=WooCommerceInstance)
def update_instance(
    instance_id: int,
    instance_update: WooCommerceInstanceUpdate,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    # Obtener propiedasdes del odoo como modulos instalados, version, etc para guardarlas en la instancia
    try:
        odoo_client = OdooClient(
            url=instance_update.odoo_url,
            db=instance_update.odoo_db,
            username=instance_update.odoo_username,
            password=instance_update.odoo_password
        )
        uid = odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pudo conectar a Odoo con las credenciales proporcionadas"
            )
        odoo_info = odoo_client.get_odoo_info()
        version_info = odoo_info.get("server_version", "Unknown")
        # Get instaled modules
        installed_modules = odoo_client.get_installed_modules()
        modules = [module.get("name") for module in installed_modules if module["name"] in [
            "sale_management", "stock", "account", "product", "website_sale"]]
        installed_modules_names = os.linesep.join(
            [module for module in modules])
        odoo_description = f"Odoo Version {version_info}\n with modules:\n \n{installed_modules_names}"
        instance_update.odoo_description = odoo_description
        """Actualizar una instancia"""

        if 'sale_management' in modules:
            odoo_webhook_url_template = "{host}/api/v1/webhook-receiver/odoo/{instance_id}/order_update"
            webhook = odoo_client.get_webhook_by_url(
                url=odoo_webhook_url_template.format(host=settings.fast_api_host,
                                                    instance_id=instance_id))
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
        )


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Eliminar una instancia"""
    deleted = crud_instance.delete_instance(
        db, instance_id=instance_id, user_id=current_user.id)
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
    instance = crud_instance.activate_instance(
        db, instance_id=instance_id, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instancia no encontrada"
        )
    return instance
