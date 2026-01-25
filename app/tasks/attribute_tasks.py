"""
Celery tasks for attribute synchronization between Odoo and WooCommerce.
"""
import logging
import asyncio
from typing import Dict, Any, List
from celery import Task
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.tasks.task_logger import log_celery_task_with_retry
from app.services.odoo_attributes import (
    get_odoo_attributes,
    get_odoo_attribute_by_id
)
from app.services.woocommerce_attributes import (
    create_or_update_woocommerce_attribute,
    sync_attribute_values
)
from app.services.odoo_service import OdooClient
from app.crud.instance import get_instance_by_id
from app.repositories.attribute_repository import AttributeSyncRepository
from app.services.woocommerce.client import get_wc_api_from_instance_config
logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.attribute_tasks.sync_attributes_from_odoo",
    max_retries=3,
    default_retry_delay=60
)
@log_celery_task_with_retry
def sync_attributes_from_odoo(
    self,
    instance_id: int,
    attribute_ids: List[int] = None,
    create_if_not_exists: bool = True,
    update_existing: bool = True
) -> Dict[str, Any]:
    """
    Sincronizar atributos desde Odoo hacia WooCommerce (tarea asíncrona)
    
    Args:
        instance_id: ID de la instancia de WooCommerce
        attribute_ids: Lista de IDs de atributos de Odoo a sincronizar (None = todos)
        create_if_not_exists: Crear atributos nuevos en WooCommerce
        update_existing: Actualizar atributos existentes en WooCommerce
    
    Returns:
        Diccionario con resultados de la sincronización
    """
    db = self.db
    
    try:
        # Obtener instancia
        instance = get_instance_by_id(db, instance_id)
        if not instance:
            raise ValueError(f"Instancia {instance_id} no encontrada")
        
        # Conectar a Odoo
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )
        
        uid = asyncio.run(odoo_client.odoo_authenticate())
        if not uid:
            raise ValueError("No se pudo autenticar con Odoo")
        
        # Obtener atributos de Odoo
        if attribute_ids:
            # Obtener atributos específicos
            odoo_attributes = []
            for attr_id in attribute_ids:
                try:
                    attr = asyncio.run(get_odoo_attribute_by_id(odoo_client, attr_id))
                    if attr:
                        odoo_attributes.append(attr)
                except Exception as e:
                    logger.error(f"Error obteniendo atributo {attr_id}: {e}")
        else:
            # Obtener todos los atributos
            odoo_attributes = asyncio.run(
                get_odoo_attributes(odoo_client, limit=500, offset=0)
            )
        
        if not odoo_attributes:
            return {
                "success": True,
                "message": "No hay atributos para sincronizar",
                "total": 0,
                "synced": 0,
                "errors": 0,
                "results": []
            }
        
        # Sincronizar cada atributo
        results = []
        synced_count = 0
        error_count = 0
        
        for odoo_attribute in odoo_attributes:
            try:
                # Crear/actualizar atributo en WooCommerce
                attribute_result = asyncio.run(
                    create_or_update_woocommerce_attribute(
                        odoo_attribute=odoo_attribute,
                        instance_id=instance_id,
                        db=db,
                        create_if_not_exists=create_if_not_exists,
                        update_existing=update_existing
                    )
                )
                
                results.append(attribute_result.dict())
                
                if not attribute_result.success:
                    error_count += 1
                elif attribute_result.action in ["created", "updated"]:
                    synced_count += 1
                    
                    # Sincronizar valores del atributo
                    if attribute_result.woocommerce_id:
                        try:
                            value_results = asyncio.run(
                                sync_attribute_values(
                                    odoo_attribute=odoo_attribute,
                                    woocommerce_attribute_id=attribute_result.woocommerce_id,
                                    instance_id=instance_id,
                                    db=db
                                )
                            )
                            
                            # Agregar resultados de valores
                            for value_result in value_results:
                                results.append({
                                    "type": "value",
                                    "parent_attribute_id": odoo_attribute.id,
                                    **value_result.dict()
                                })
                        except Exception as e:
                            logger.error(
                                f"Error sincronizando valores del atributo {odoo_attribute.id}: {e}"
                            )
                
            except Exception as e:
                logger.error(f"Error sincronizando atributo {odoo_attribute.id}: {e}")
                error_count += 1
                results.append({
                    "odoo_attribute_id": odoo_attribute.id,
                    "error": True,
                    "message": f"Error: {str(e)}"
                })
        
        return {
            "success": True,
            "message": f"Sincronizados {synced_count} atributos, {error_count} errores",
            "total": len(odoo_attributes),
            "synced": synced_count,
            "errors": error_count,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error en sincronización de atributos: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "total": 0,
            "synced": 0,
            "errors": 1
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.attribute_tasks.sync_single_attribute",
    max_retries=3,
    default_retry_delay=30
)
@log_celery_task_with_retry
def sync_single_attribute(
    self,
    instance_id: int,
    odoo_attribute_id: int,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    odoo_config: Dict[str, str] = None,
    wc_config: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Sincronizar un solo atributo desde Odoo hacia WooCommerce
    
    Args:
        instance_id: ID de la instancia de WooCommerce
        odoo_attribute_id: ID del atributo en Odoo
        create_if_not_exists: Crear si no existe en WooCommerce
        update_existing: Actualizar si ya existe en WooCommerce
    
    Returns:
        Resultado de la sincronización
    """
    db = self.db
    
    try:
        # Obtener instancia
        instance = get_instance_by_id(db, instance_id)
        wcapi = None
        if wc_config:
            wcapi = get_wc_api_from_instance_config(wc_config)
        if not instance:
            raise ValueError(f"Instancia {instance_id} no encontrada")
        
        # Conectar a Odoo
        odoo_client = OdooClient(
            url=odoo_config.get("url") if odoo_config else instance.odoo_url,
            db=odoo_config.get("db") if odoo_config else instance.odoo_db,
            username=odoo_config.get("username") if odoo_config else instance.odoo_username,
            password=odoo_config.get("password") if odoo_config else instance.odoo_password
        )
        
        uid = asyncio.run(odoo_client.odoo_authenticate())
        if not uid:
            raise ValueError("No se pudo autenticar con Odoo")
        
        # Obtener atributo de Odoo
        odoo_attribute = asyncio.run(
            get_odoo_attribute_by_id(odoo_client, odoo_attribute_id)
        )
        
        if not odoo_attribute:
            raise ValueError(f"Atributo {odoo_attribute_id} no encontrado en Odoo")
        
        # Sincronizar atributo a WooCommerce
        attribute_result = asyncio.run(
            create_or_update_woocommerce_attribute(
                odoo_attribute=odoo_attribute,
                instance_id=instance_id,
                db=db,
                create_if_not_exists=create_if_not_exists,
                update_existing=update_existing,
                wcapi=wcapi
            )
        )
        
        # Sincronizar valores del atributo
        value_results = []
        if attribute_result.woocommerce_id and attribute_result.success:
            value_results = asyncio.run(
                sync_attribute_values(
                    odoo_attribute=odoo_attribute,
                    woocommerce_attribute_id=attribute_result.woocommerce_id,
                    instance_id=instance_id,
                    db=db
                )
            )
        
        return {
            "success": attribute_result.success,
            "attribute": attribute_result.dict(),
            "values": [v.dict() for v in value_results],
            "message": attribute_result.message
        }
        
    except Exception as e:
        logger.error(f"Error sincronizando atributo {odoo_attribute_id}: {e}")
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "error": True
        }


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.attribute_tasks.get_attribute_sync_status",
    max_retries=1
)
def get_attribute_sync_status(self, instance_id: int, odoo_attribute_id: int) -> Dict[str, Any]:
    """
    Obtener estado de sincronización de un atributo
    
    Args:
        instance_id: ID de la instancia
        odoo_attribute_id: ID del atributo en Odoo
    
    Returns:
        Estado de sincronización
    """
    db = self.db
    repository = AttributeSyncRepository(db)
    
    try:
        sync = repository.get_attribute_sync_by_odoo_id(
            instance_id=instance_id,
            odoo_attribute_id=odoo_attribute_id
        )
        
        if sync:
            return {
                "found": True,
                "sync": {
                    "odoo_attribute_id": sync.odoo_attribute_id,
                    "woocommerce_id": sync.woocommerce_id,
                    "slug": sync.slug,
                    "created": sync.created,
                    "updated": sync.updated,
                    "error": sync.error,
                    "message": sync.message,
                    "sync_date": sync.sync_date.isoformat() if sync.sync_date else None,
                }
            }
        else:
            return {
                "found": False,
                "message": "Atributo no sincronizado"
            }
    except Exception as e:
        logger.error(f"Error obteniendo estado de sincronización: {e}")
        return {
            "found": False,
            "error": str(e)
        }
