"""
Endpoints mejorados para tracking de tareas Celery.

Incluye:
- Consulta detallada de tareas individuales
- Cancelación de tareas
- Estadísticas de colas
- Tareas activas
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

from app.db.session import get_db
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.tasks.task_monitoring import (
    get_task_info,
    revoke_task,
    get_running_tasks,
    get_queue_stats,
    cleanup_old_task_logs
)
from app.repositories import TaskLogRepository

router = APIRouter()


# ==================== Schemas ====================

class TaskDetailResponse(BaseModel):
    """Respuesta detallada de una tarea"""
    task_id: str
    task_name: Optional[str]
    instance_id: Optional[int]
    celery_state: str
    db_status: Optional[str]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_seconds: Optional[float]
    found_in_db: bool


class RunningTasksResponse(BaseModel):
    """Tareas actualmente en ejecución"""
    active_count: int
    tasks: List[Dict[str, Any]]


class QueueStatsResponse(BaseModel):
    """Estadísticas de colas"""
    queues: Dict[str, Dict[str, int]]


class TaskActionResponse(BaseModel):
    """Respuesta de acción sobre tarea"""
    success: bool
    message: str
    task_id: str


# ==================== Endpoints ====================

@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task_detail(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener información detallada de una tarea específica.
    
    Combina información de Celery (estado actual) y BD (histórico completo).
    """
    try:
        task_info = get_task_info(task_id)
        
        # Verificar permisos de instancia si la tarea tiene instance_id
        if task_info.get('instance_id'):
            # Aquí podrías verificar que el usuario tenga acceso a esa instancia
            pass
        
        return TaskDetailResponse(**task_info)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving task: {str(e)}")


@router.delete("/tasks/{task_id}/cancel", response_model=TaskActionResponse)
async def cancel_task(
    task_id: str,
    terminate: bool = Query(False, description="Terminar worker process (peligroso)"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Cancelar una tarea en ejecución.
    
    **CUIDADO**: `terminate=True` mata el proceso worker, puede causar corrupción de datos.
    """
    try:
        success = revoke_task(task_id, terminate=terminate)
        
        if success:
            return TaskActionResponse(
                success=True,
                message=f"Task {task_id} cancelled successfully",
                task_id=task_id
            )
        else:
            return TaskActionResponse(
                success=False,
                message=f"Task {task_id} cannot be cancelled (already completed or failed)",
                task_id=task_id
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling task: {str(e)}")


@router.get("/tasks/active/all", response_model=RunningTasksResponse)
async def get_active_tasks(
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener todas las tareas actualmente en ejecución.
    
    Útil para ver qué está procesando el sistema en tiempo real.
    """
    try:
        running = get_running_tasks()
        return RunningTasksResponse(**running)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving active tasks: {str(e)}")


@router.get("/queues/stats", response_model=QueueStatsResponse)
async def get_queue_statistics(
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener estadísticas de las colas de Celery.
    
    Muestra cuántas tareas hay pendientes en cada cola.
    """
    try:
        stats = get_queue_stats()
        return QueueStatsResponse(queues=stats)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving queue stats: {str(e)}")


@router.post("/tasks/cleanup")
async def cleanup_tasks(
    days: int = Query(30, ge=1, le=365, description="Eliminar logs más antiguos que N días"),
    current_user: Admin = Depends(get_current_user)
):
    """
    Limpiar logs de tareas antiguas.
    
    Solo elimina registros de BD, no afecta tareas en ejecución.
    """
    try:
        result = cleanup_old_task_logs(days)
        
        return {
            "success": True,
            "message": f"Deleted {result['deleted']} task logs older than {days} days",
            "deleted_count": result['deleted']
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cleaning up tasks: {str(e)}")


@router.get("/tasks/summary/stats")
async def get_task_summary(
    hours: int = Query(24, ge=1, le=168, description="Últimas N horas"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener resumen estadístico de tareas.
    
    Útil para dashboards y monitoreo.
    """
    try:
        from datetime import timedelta
        from sqlalchemy import func, literal_column
        from app.models.admin import CeleryTaskLog
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Contar por status
        status_counts = db.query(
            CeleryTaskLog.status,
            func.count(CeleryTaskLog.id).label('count')
        ).filter(
            CeleryTaskLog.created_at >= cutoff
        ).group_by(
            CeleryTaskLog.status
        ).all()
        
        # Contar por task_name
        task_counts = db.query(
            CeleryTaskLog.task_name,
            func.count(CeleryTaskLog.id).label('count')
        ).filter(
            CeleryTaskLog.created_at >= cutoff
        ).group_by(
            CeleryTaskLog.task_name
        ).all()
        
        # Calcular duración promedio
        avg_duration = db.query(
            func.avg(
                func.timestampdiff(
                    literal_column("SECOND"),
                    CeleryTaskLog.started_at,
                    CeleryTaskLog.completed_at
                )
            )
        ).filter(
            CeleryTaskLog.created_at >= cutoff,
            CeleryTaskLog.completed_at.isnot(None)
        ).scalar()
        
        return {
            "time_range_hours": hours,
            "status_breakdown": {
                status: count for status, count in status_counts
            },
            "task_breakdown": {
                task_name: count for task_name, count in task_counts
            },
            "average_duration_seconds": float(avg_duration) if avg_duration else None,
            "total_tasks": sum(count for _, count in status_counts)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")
