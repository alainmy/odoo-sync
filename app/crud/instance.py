from sqlalchemy.orm import Session
from app.models.admin import WooCommerceInstance
from app.schemas.instance import WooCommerceInstanceCreate, WooCommerceInstanceUpdate
from typing import List, Optional


def get_instances_by_user(db: Session, user_id: int, skip: int = 0, limit: int = 100) -> List[WooCommerceInstance]:
    """Obtener todas las instancias de un usuario"""
    return db.query(WooCommerceInstance).filter(
        WooCommerceInstance.user_id == user_id
    ).offset(skip).limit(limit).all()


def get_instance(db: Session, instance_id: int, user_id: int) -> Optional[WooCommerceInstance]:
    """Obtener una instancia específica del usuario"""
    return db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id,
        WooCommerceInstance.user_id == user_id
    ).first()


def get_instance_by_id(db: Session, instance_id: int) -> Optional[WooCommerceInstance]:
    """Obtener una instancia por ID sin validar usuario (para tareas Celery)"""
    return db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id
    ).first()


def get_active_instance(db: Session, user_id: int) -> Optional[WooCommerceInstance]:
    """Obtener la instancia activa del usuario"""
    return db.query(WooCommerceInstance).filter(
        WooCommerceInstance.user_id == user_id,
        WooCommerceInstance.is_active == True
    ).first()


def create_instance(db: Session, instance: WooCommerceInstanceCreate, user_id: int) -> WooCommerceInstance:
    """Crear nueva instancia para un usuario"""
    # Si es la primera instancia o se marca como activa, desactivar otras
    if instance.is_active:
        db.query(WooCommerceInstance).filter(
            WooCommerceInstance.user_id == user_id
        ).update({"is_active": False})
    
    db_instance = WooCommerceInstance(
        **instance.model_dump(),
        user_id=user_id
    )
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)
    return db_instance


def update_instance(
    db: Session, 
    instance_id: int, 
    user_id: int, 
    instance_update: WooCommerceInstanceUpdate
) -> Optional[WooCommerceInstance]:
    """Actualizar una instancia"""
    db_instance = get_instance(db, instance_id, user_id)
    if not db_instance:
        return None
    
    update_data = instance_update.model_dump(exclude_unset=True)
    
    # Si se activa esta instancia, desactivar las demás
    if update_data.get("is_active"):
        db.query(WooCommerceInstance).filter(
            WooCommerceInstance.user_id == user_id,
            WooCommerceInstance.id != instance_id
        ).update({"is_active": False})
    
    for field, value in update_data.items():
        setattr(db_instance, field, value)
    
    db.commit()
    db.refresh(db_instance)
    return db_instance


def delete_instance(db: Session, instance_id: int, user_id: int) -> bool:
    """Eliminar una instancia"""
    db_instance = get_instance(db, instance_id, user_id)
    if not db_instance:
        return False
    
    db.delete(db_instance)
    db.commit()
    return True


def activate_instance(db: Session, instance_id: int, user_id: int) -> Optional[WooCommerceInstance]:
    """Activar una instancia (y desactivar las demás)"""
    db_instance = get_instance(db, instance_id, user_id)
    if not db_instance:
        return None
    
    # Desactivar todas las instancias del usuario
    db.query(WooCommerceInstance).filter(
        WooCommerceInstance.user_id == user_id
    ).update({"is_active": False})
    
    # Activar esta instancia
    db_instance.is_active = True
    db.commit()
    db.refresh(db_instance)
    return db_instance
