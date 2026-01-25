"""
Mejoras al sistema de tracking de tareas Celery.

Agrega:
1. Hooks on_success/on_failure para callbacks limpios
2. Actualización de progreso en tiempo real
3. Helper para retornar task_id + metadata
4. Integración con alertas para errores críticos
"""
import logging
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from celery import Task
from celery.signals import task_success, task_failure, task_retry, task_revoked

from app.db.session import SessionLocal
from app.repositories import TaskLogRepository
from app.core.alerts import send_task_error_alert

logger = logging.getLogger(__name__)


# ==================== Signal Handlers ====================

@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """
    Handler ejecutado cuando una tarea termina exitosamente.
    Alternativa a actualizar desde el decorador.
    """
    task_id = sender.request.id
    task_name = sender.name
    
    logger.info(f"[SIGNAL] Task {task_name} [{task_id}] completed successfully")
    
    # Aquí podrías agregar lógica adicional como:
    # - Enviar notificación de éxito
    # - Actualizar métricas
    # - Disparar siguiente tarea en workflow


@task_failure.connect
def task_failure_handler(sender=None, exception=None, **kwargs):
    """
    Handler ejecutado cuando una tarea falla definitivamente.
    """
    task_id = sender.request.id
    task_name = sender.name
    retries = sender.request.retries
    max_retries = sender.max_retries
    
    logger.error(
        f"[SIGNAL] Task {task_name} [{task_id}] failed permanently "
        f"after {retries} retries: {exception}"
    )
    
    # Enviar alerta crítica
    send_task_error_alert(
        task_name=task_name,
        error=exception,
        task_id=task_id,
        instance_id=None,  # Extraer de kwargs si está disponible
        retries=retries,
        max_retries=max_retries
    )


@task_retry.connect
def task_retry_handler(sender=None, reason=None, **kwargs):
    """
    Handler ejecutado cuando una tarea va a reintentar.
    """
    task_id = sender.request.id
    task_name = sender.name
    retries = sender.request.retries
    
    logger.warning(
        f"[SIGNAL] Task {task_name} [{task_id}] retrying "
        f"(attempt {retries + 1}): {reason}"
    )


@task_revoked.connect
def task_revoked_handler(sender=None, terminated=None, signum=None, **kwargs):
    """
    Handler ejecutado cuando una tarea es revocada/cancelada.
    """
    task_id = sender.request.id
    task_name = sender.name
    
    logger.warning(
        f"[SIGNAL] Task {task_name} [{task_id}] was revoked "
        f"(terminated={terminated}, signal={signum})"
    )
    
    # Actualizar estado en BD
    db = SessionLocal()
    try:
        task_log_repo = TaskLogRepository(db)
        task_log_repo.update_task_log(
            task_id=task_id,
            status="revoked",
            error_message=f"Task revoked (signal={signum})",
            completed_at=datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Error updating revoked task status: {e}")
    finally:
        db.close()


# ==================== Helper Functions ====================

def create_task_response(task, instance_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Helper para crear respuesta consistente al encolar tarea.
    
    Uso:
        task = sync_product.delay(product_id)
        return create_task_response(task, instance_id=1)
    
    Returns:
        {
            "task_id": "uuid",
            "status": "queued",
            "instance_id": 1,
            "created_at": "2026-01-19T...",
            "check_url": "/api/v1/sync/tasks/{task_id}"
        }
    """
    return {
        "task_id": task.id,
        "status": "queued",
        "instance_id": instance_id,
        "created_at": datetime.utcnow().isoformat(),
        "check_url": f"/api/v1/sync/tasks/{task.id}"
    }


def update_task_progress(
    task: Task,
    current: int,
    total: int,
    message: str = None,
    metadata: Dict[str, Any] = None
):
    """
    Actualizar progreso de tarea en tiempo real.
    
    Uso dentro de una tarea:
        for i, item in enumerate(items):
            update_task_progress(self, i + 1, len(items), f"Processing {item}")
            process_item(item)
    """
    progress_data = {
        'current': current,
        'total': total,
        'percentage': round((current / total * 100), 2) if total > 0 else 0,
    }
    
    if message:
        progress_data['message'] = message
    
    if metadata:
        progress_data['metadata'] = metadata
    
    task.update_state(
        state='PROGRESS',
        meta=progress_data
    )


def get_task_info(task_id: str) -> Dict[str, Any]:
    """
    Obtener información completa de una tarea (Celery + BD).
    
    Combina:
    - Estado de Celery (PENDING, STARTED, SUCCESS, FAILURE)
    - Registro de BD (task_log con detalles completos)
    
    Returns:
        {
            "task_id": "uuid",
            "celery_state": "SUCCESS",
            "db_status": "success",
            "result": {...},
            "error": None,
            "created_at": "...",
            "started_at": "...",
            "completed_at": "...",
            "duration_seconds": 12.5
        }
    """
    from celery.result import AsyncResult
    
    # Estado de Celery
    task_result = AsyncResult(task_id)
    celery_state = task_result.state
    celery_result = task_result.result if task_result.ready() else None
    
    # Estado de BD
    db = SessionLocal()
    try:
        task_log_repo = TaskLogRepository(db)
        db_log = task_log_repo.get_task_log(task_id)
        
        if not db_log:
            return {
                "task_id": task_id,
                "celery_state": celery_state,
                "db_status": None,
                "found_in_db": False,
                "result": celery_result,
                "error": str(task_result.info) if celery_state == 'FAILURE' else None
            }
        
        # Calcular duración
        duration = None
        if db_log.started_at and db_log.completed_at:
            duration = (db_log.completed_at - db_log.started_at).total_seconds()
        
        return {
            "task_id": task_id,
            "task_name": db_log.task_name,
            "instance_id": db_log.instance_id,
            "celery_state": celery_state,
            "db_status": db_log.status,
            "result": db_log.result or celery_result,
            "error": db_log.error_message,
            "created_at": db_log.created_at.isoformat() if db_log.created_at else None,
            "started_at": db_log.started_at.isoformat() if db_log.started_at else None,
            "completed_at": db_log.completed_at.isoformat() if db_log.completed_at else None,
            "duration_seconds": duration,
            "found_in_db": True
        }
        
    finally:
        db.close()


def revoke_task(task_id: str, terminate: bool = False) -> bool:
    """
    Cancelar una tarea en ejecución.
    
    Args:
        task_id: ID de la tarea
        terminate: Si True, mata el worker process (peligroso)
    
    Returns:
        True si se canceló exitosamente
    """
    from celery.result import AsyncResult
    
    task = AsyncResult(task_id)
    
    if task.state in ['PENDING', 'STARTED', 'RETRY']:
        task.revoke(terminate=terminate)
        logger.info(f"Task {task_id} revoked (terminate={terminate})")
        return True
    else:
        logger.warning(f"Cannot revoke task {task_id} in state {task.state}")
        return False


# ==================== Task Monitoring ====================

def get_running_tasks() -> Dict[str, Any]:
    """
    Obtener todas las tareas actualmente en ejecución.
    
    Returns:
        {
            "active_count": 5,
            "tasks": [
                {
                    "id": "uuid",
                    "name": "sync_product",
                    "worker": "celery@hostname"
                },
                ...
            ]
        }
    """
    from app.celery_app import celery_app
    
    inspect = celery_app.control.inspect()
    active = inspect.active()
    
    if not active:
        return {"active_count": 0, "tasks": []}
    
    tasks = []
    for worker, task_list in active.items():
        for task_info in task_list:
            tasks.append({
                "id": task_info.get('id'),
                "name": task_info.get('name'),
                "worker": worker,
                "args": task_info.get('args'),
                "kwargs": task_info.get('kwargs')
            })
    
    return {
        "active_count": len(tasks),
        "tasks": tasks
    }


def get_queue_stats() -> Dict[str, Any]:
    """
    Obtener estadísticas de las colas.
    
    Returns:
        {
            "sync_queue": {"messages": 10},
            "webhook_queue": {"messages": 0},
            ...
        }
    """
    from app.celery_app import celery_app
    
    inspect = celery_app.control.inspect()
    
    # Obtener mensajes reservados por worker
    reserved = inspect.reserved()
    scheduled = inspect.scheduled()
    
    stats = {}
    
    # Contar mensajes por cola
    if reserved:
        for worker, tasks in reserved.items():
            for task in tasks:
                queue = task.get('delivery_info', {}).get('routing_key', 'default')
                if queue not in stats:
                    stats[queue] = {"reserved": 0, "scheduled": 0}
                stats[queue]["reserved"] += 1
    
    if scheduled:
        for worker, tasks in scheduled.items():
            for task in tasks:
                queue = task.get('delivery_info', {}).get('routing_key', 'default')
                if queue not in stats:
                    stats[queue] = {"reserved": 0, "scheduled": 0}
                stats[queue]["scheduled"] += 1
    
    return stats


# ==================== Cleanup ====================

def cleanup_old_task_logs(days: int = 30) -> Dict[str, int]:
    """
    Limpiar logs de tareas antiguas.
    
    Args:
        days: Eliminar logs más antiguos que N días
    
    Returns:
        {"deleted": 150}
    """
    db = SessionLocal()
    try:
        task_log_repo = TaskLogRepository(db)
        
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Eliminar logs antiguos
        deleted = db.query(task_log_repo.model).filter(
            task_log_repo.model.created_at < cutoff_date
        ).delete()
        
        db.commit()
        
        logger.info(f"Deleted {deleted} task logs older than {days} days")
        
        return {"deleted": deleted}
        
    finally:
        db.close()
