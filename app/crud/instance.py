import logging
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.admin import WooCommerceInstance
from app.schemas.instance import WooCommerceInstanceCreate, WooCommerceInstanceUpdate
from typing import List, Optional

from app.models.webhook_models import WebhookConfig
from app.repositories.webhook_config_repository import WebhookConfigRepository
from app.schemas.webhook_schemas import WebhookConfigCreate

logger = logging.getLogger(__name__)


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
    # Hook para cuando se elimine un producto
    topics = ["product.deleted"]
    for t in topics:
        exiting_hook = db.query(WebhookConfig).filter(
            WebhookConfig.instance_id == db_instance.id,
            WebhookConfig.topic == t
        ).first()
        if not exiting_hook:
            create_hook_for_instance(
                db,
                instance=db_instance,
                name=f"Product Deleted Hook {t}",
                topic=t
            )
    return db_instance


def create_hook_for_instance(db: Session,
                             instance: WooCommerceInstance,
                             name: str = "Product Deleted Hook",
                             topic: str = "product.deleted",
                             url_template: str = "/api/v1/webhook-receiver/wc/{instance_id}/{topic}"
                             ) -> None:
    """Crear un webhook para eliminar productos en WooCommerce"""
    repo = WebhookConfigRepository(db)
    delivery_url = f"https://diphthongous-ponderingly-hilaria.ngrok-free.dev{url_template.format(instance_id=instance.id, topic=topic)}"
    config = WebhookConfigCreate(
        instance_id=instance.id,
        name=name,
        topic=topic,
        delivery_url=delivery_url,
        active=True
    )
    new_webhook = repo.create(config)
    
    from app.tasks.instance_tasks import create_wwc_webhooks_for_instance
    task = create_wwc_webhooks_for_instance.apply_async(
        args=[config.model_dump(), new_webhook.id],
        kwargs={"instance_id": instance.id},
        queue='sync_queue'
    )
    return new_webhook


# def create_wwc_webhooks_for_instance(db: Session,
#                                      config: WebhookConfigCreate,
#                                      new_webhook: WebhookConfig,
#                                      repo: WebhookConfigRepository,
#                                      instance: WooCommerceInstance) -> None:
#     """Crear webhooks para una instancia (ejemplo para productos)"""
#     wc_config = {
#         "url": instance.woocommerce_url,
#         "consumer_key": instance.woocommerce_consumer_key,
#         "consumer_secret": instance.woocommerce_consumer_secret
#     }
#     wcapi = create_wc_api_client(wc_config)
#     service = WebhookService(db)
#     wc_response = service.create_webhook_in_woocommerce(wcapi, config)
#     if wc_response and wc_response.get('id'):
#         # Update local webhook with WooCommerce ID
#         repo.update_wc_webhook_id(
#             new_webhook.id, wc_response.get('id'))

#         # Refresh to get updated data
#         db.refresh(new_webhook)
#         logger.info(
#             f"Created webhook in WooCommerce with ID {wc_response.get('id')}")
#     else:
#         logger.warning(
#             f"Webhook created locally but failed to create in WooCommerce")


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
    topics = ["product.deleted"]
    for t in topics:
        exiting_hook = db.query(WebhookConfig).filter(
            WebhookConfig.instance_id == db_instance.id,
            WebhookConfig.topic == t
        ).first()
        if not exiting_hook:
            create_hook_for_instance(
                db,
                instance=db_instance,
                name=f"Product Deleted Hook {t}",
                topic=t
            )
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
