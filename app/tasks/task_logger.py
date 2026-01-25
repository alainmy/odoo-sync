"""
Decorador para logging automático de tareas Celery.
"""
import functools
import logging
from typing import Callable, Any
from datetime import datetime
from celery import Task
from app.db.session import SessionLocal
from app.repositories import TaskLogRepository

logger = logging.getLogger(__name__)


def log_celery_task(func: Callable) -> Callable:
    """
    Decorador que automáticamente registra la ejecución de tareas Celery en CeleryTaskLog.
    
    Uso:
        @celery_app.task
        @log_celery_task
        def my_task(arg1, arg2):
            ...
    """
    @functools.wraps(func)
    def wrapper(self: Task, *args, **kwargs) -> Any:
        db = SessionLocal()
        sync_repo = TaskLogRepository(db)
        task_log = None
        
        try:
            # Extraer instance_id de los argumentos de la tarea
            instance_id = kwargs.get('instance_id')
            if not instance_id and len(args) > 1 and isinstance(args[1], int):
                instance_id = args[1]
            
            # Si no hay instance_id, usar None (para tasks que no lo requieren)
            if not instance_id:
                logger.warning(f"Task {self.name} called without instance_id")
                instance_id = None
            
            # Crear registro de inicio de tarea
            task_log = sync_repo.create_task_log(
                task_id=self.request.id,
                task_name=self.name,
                instance_id=instance_id,
                task_args=list(args) if args else [],
                task_kwargs=kwargs if kwargs else {},
                status="started"
            )
            logger.info(f"Task {self.name} [{self.request.id}] started")
            
            # Ejecutar la tarea
            result = func(self, *args, **kwargs)
            
            # Actualizar como exitosa
            sync_repo.update_task_log(
                task_id=self.request.id,
                status="success",
                result={"data": result} if result else None,
                completed_at=datetime.utcnow()
            )
            logger.info(f"Task {self.name} [{self.request.id}] completed successfully")
            
            return result
            
        except Exception as exc:
            # Registrar el error
            error_message = str(exc)
            logger.error(f"Task {self.name} [{self.request.id}] failed: {error_message}")
            
            if task_log:
                sync_repo.update_task_log(
                    task_id=self.request.id,
                    status="failure",
                    error_message=error_message,
                    completed_at=datetime.utcnow()
                )
            
            # Re-lanzar la excepción para que Celery maneje los reintentos
            raise
            
        finally:
            db.close()
    
    return wrapper


def log_celery_task_with_retry(func: Callable) -> Callable:
    """
    Decorador que registra tareas Celery incluyendo reintentos.
    
    Uso:
        @celery_app.task(bind=True, max_retries=3)
        @log_celery_task_with_retry
        def my_task(self, arg1, arg2):
            ...
    """
    @functools.wraps(func)
    def wrapper(self: Task, *args, **kwargs) -> Any:
        db = SessionLocal()
        sync_repo = TaskLogRepository(db)
        task_log = None
        
        try:
            # Extraer parent_task_id de múltiples fuentes en orden de prioridad:
            # 1. Celery native (si usas chain/chord)
            # 2. Headers personalizados
            # 3. Argumentos de la función
            parent_task_id = (
                getattr(self.request, 'parent_id', None) or
                self.request.headers.get('parent_task_id') or
                kwargs.get('parent_task_id')
            )
            
            # Extraer instance_id de los argumentos de la tarea
            # Buscar primero en kwargs
            instance_id = kwargs.get('instance_id')
            
            # Si no está en kwargs, intentar extraer de args
            # Para diferentes tipos de tareas, instance_id puede estar en diferentes posiciones:
            # - sync_single_attribute: args[0] es instance_id
            # - sync_product_to_woocommerce: args[1] es instance_id (args[0] es product_data)
            # - sync_category_to_woocommerce: args[1] es instance_id (args[0] es category_data)
            if not instance_id and args:
                # Intentar args[0] primero (para attribute tasks, etc)
                if len(args) > 0 and isinstance(args[0], int):
                    instance_id = args[0]
                # Si args[0] no es int, intentar args[1] (para product/category tasks)
                elif len(args) > 1 and isinstance(args[1], int):
                    instance_id = args[1]
            
            # Si no hay instance_id, usar None (para tasks que no lo requieren)
            if not instance_id:
                logger.warning(f"Task {self.name} called without instance_id")
                instance_id = None
            
            # Obtener o crear registro de tarea
            existing_log = sync_repo.get_task_log(self.request.id)
            
            if existing_log:
                # Es un reintento - solo actualizar status
                sync_repo.update_task_log(
                    task_id=self.request.id,
                    status="retry"
                )
                logger.info(f"Task {self.name} [{self.request.id}] retry attempt (parent: {parent_task_id})")
            else:
                # Primera ejecución - intentar crear registro
                try:
                    task_log = sync_repo.create_task_log(
                        task_id=self.request.id,
                        task_name=self.name,
                        instance_id=instance_id,
                        parent_task_id=parent_task_id,
                        task_args=list(args) if args else [],
                        task_kwargs=kwargs if kwargs else {},
                        status="started"
                    )
                    if parent_task_id:
                        logger.info(f"Task {self.name} [{self.request.id}] started (child of {parent_task_id})")
                    else:
                        logger.info(f"Task {self.name} [{self.request.id}] started")
                except Exception as create_error:
                    # Si falla la creación (ej. duplicate key), hacer rollback e intentar actualizar
                    logger.warning(f"Failed to create task log, attempting update: {create_error}")
                    db.rollback()
                    existing_log = sync_repo.get_task_log(self.request.id)
                    if existing_log:
                        sync_repo.update_task_log(
                            task_id=self.request.id,
                            status="retry"
                        )
                    else:
                        # Si aún no existe, re-lanzar el error
                        raise
            
            # Ejecutar la tarea
            result = func(self, *args, **kwargs)
            
            # Actualizar como exitosa
            sync_repo.update_task_log(
                task_id=self.request.id,
                status="success" if result.get('success') else "failure",
                result={"data": result} if result else None,
                completed_at=datetime.utcnow()
            )
            logger.info(f"Task {self.name} [{self.request.id}] {result.get('success')}")
            
            return result
            
        except Exception as exc:
            # Registrar el error
            error_message = f"{type(exc).__name__}: {str(exc)}"
            logger.error(f"Task {self.name} [{self.request.id}] failed: {error_message}")
            
            # Determinar si habrá más reintentos
            retries = self.request.retries
            max_retries = self.max_retries
            
            if retries < max_retries:
                # Habrá más reintentos
                status = "retry"
                logger.info(f"Task {self.name} [{self.request.id}] will retry ({retries + 1}/{max_retries})")
            else:
                # No más reintentos, fallo definitivo
                status = "failure"
                logger.error(f"Task {self.name} [{self.request.id}] failed permanently after {retries} retries")
            
            sync_repo.update_task_log(
                task_id=self.request.id,
                status=status,
                error_message=error_message,
                completed_at=datetime.utcnow() if status == "failure" else None
            )
            
            # Re-lanzar la excepción para que Celery maneje los reintentos
            raise
            
        finally:
            db.close()
    
    return wrapper
