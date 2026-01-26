"""Helper functions for WooCommerce instance management."""

from typing import Dict, Tuple
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.crud import instance as crud_instance
from app.models.admin import Admin, WooCommerceInstance


def get_active_instance_id(db: Session, current_user: Admin) -> int:
    """
    Get the ID of the active WooCommerce instance for the current user.
    
    Args:
        db: Database session
        current_user: Current authenticated user
        
    Returns:
        int: Active instance ID
        
    Raises:
        HTTPException: If no active instance is configured
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa configurada. Por favor, configura una instancia de WooCommerce primero."
        )
    return instance.id


def get_active_instance(db: Session, current_user: Admin) -> WooCommerceInstance:
    """
    Get the active WooCommerce instance for the current user.
    
    Args:
        db: Database session
        current_user: Current authenticated user
        
    Returns:
        WooCommerceInstance: Active instance object
        
    Raises:
        HTTPException: If no active instance is configured
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa configurada. Por favor, configura una instancia de WooCommerce primero."
        )
    return instance


def get_instance_configs(
    db: Session, 
    current_user: Admin
) -> Tuple[Dict, Dict, int]:
    """
    Get Odoo and WooCommerce configurations for the active instance.
    
    Args:
        db: Database session
        current_user: Current authenticated user
        
    Returns:
        Tuple containing:
            - odoo_config (Dict): Odoo connection configuration
            - wc_config (Dict): WooCommerce connection configuration
            - instance_id (int): Active instance ID
            
    Raises:
        HTTPException: If no active instance is configured
    """
    instance = get_active_instance(db, current_user)
    
    odoo_config = {
        "url": instance.odoo_url,
        "db": instance.odoo_db,
        "username": instance.odoo_username,
        "password": instance.odoo_password,
    }
    
    wc_config = {
        "url": instance.woocommerce_url,
        "consumer_key": instance.woocommerce_consumer_key,
        "consumer_secret": instance.woocommerce_consumer_secret,
    }
    
    return odoo_config, wc_config, instance.id


def ensure_active_instance(db: Session, user_id: int) -> WooCommerceInstance:
    """
    Ensure an active instance exists for the user or raise error.
    
    Args:
        db: Database session
        user_id: User ID to check
        
    Returns:
        WooCommerceInstance: Active instance object
        
    Raises:
        HTTPException: If no active instance is configured
    """
    instance = crud_instance.get_active_instance(db, user_id=user_id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No active instance configured"
        )
    return instance
