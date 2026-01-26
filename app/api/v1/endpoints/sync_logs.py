"""
API endpoints para consultar logs de sincronización.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.db.session import get_db
from app.repositories import (
    ProductSyncRepository, 
    CategorySyncRepository, 
    TagSyncRepository,
    WebhookRepository,
    TaskLogRepository
)
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin, WebhookLog
from app.utils.instance_helpers import get_active_instance_id

router = APIRouter()


# ==================== Schemas ====================

class WebhookLogResponse(BaseModel):
    """Respuesta de log de webhook"""
    id: int
    event_id: str
    event_type: str
    instance_id: Optional[int]
    payload_hash: str
    status: str
    retry_count: int
    error_message: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class TaskLogResponse(BaseModel):
    """Respuesta de log de tarea Celery"""
    id: int
    task_id: str
    task_name: str
    status: str
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[dict]
    
    class Config:
        from_attributes = True


class ProductSyncResponse(BaseModel):
    """Respuesta de sincronización de producto"""
    id: int
    odoo_id: int
    woocommerce_id: int
    odoo_name: Optional[str]
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: str
    error_details: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class CategorySyncResponse(BaseModel):
    """Respuesta de sincronización de categoría"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    woocommerce_id: int
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: str
    error_details: Optional[str]
    
    class Config:
        from_attributes = True


class TagSyncResponse(BaseModel):
    """Respuesta de sincronización de tag"""
    id: int
    odoo_id: int
    odoo_name: Optional[str]
    woocommerce_id: int
    created: bool
    updated: bool
    skipped: bool
    error: bool
    message: str
    error_details: Optional[str]
    
    class Config:
        from_attributes = True


class SyncStatisticsResponse(BaseModel):
    """Estadísticas generales de sincronización"""
    webhooks: dict
    tasks: dict
    products: dict
    categories: dict


# ==================== Endpoints ====================

@router.get("/webhooks", response_model=List[WebhookLogResponse])
async def get_webhook_logs(
    status: Optional[str] = Query(None, description="Filtrar por status: pending, processing, completed, failed"),
    event_type: Optional[str] = Query(None, description="Filtrar por tipo de evento"),
    limit: int = Query(100, le=1000, description="Límite de resultados"),
    skip: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener logs de webhooks recibidos.
    
    Permite filtrar por status, tipo de evento y paginación.
    """
    instance_id = get_active_instance_id(db, current_user)
    webhook_repo = WebhookRepository(db)
    
    logs = webhook_repo.get_webhook_logs(
        instance_id=instance_id,
        status=status,
        event_type=event_type,
        limit=limit,
        offset=skip
    )
    
    return logs


@router.get("/webhooks/{webhook_id}", response_model=WebhookLogResponse)
async def get_webhook_log(
    webhook_id: str,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener un log de webhook específico por su ID.
    Solo permite acceso a webhooks de la instancia activa del usuario.
    """
    instance_id = get_active_instance_id(db, current_user)
    webhook_repo = WebhookRepository(db)
    log = webhook_repo.get_webhook_log_by_event_id(webhook_id)
    
    if not log:
        raise HTTPException(status_code=404, detail=f"Webhook log {webhook_id} no encontrado")
    
    # Verificar que el webhook pertenece a la instancia del usuario
    if log.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Webhook log {webhook_id} no encontrado")
    
    return log


@router.delete("/webhooks/cleanup")
async def cleanup_old_webhooks(
    days: int = Query(30, ge=1, le=365, description="Días de antigüedad para eliminar"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Eliminar logs de webhooks antiguos completados de la instancia del usuario.
    
    Por defecto elimina webhooks completados de más de 30 días.
    Solo afecta a la instancia activa del usuario actual.
    """
    instance_id = get_active_instance_id(db, current_user)
    webhook_repo = WebhookRepository(db)
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Eliminar solo webhooks de la instancia del usuario
    deleted = db.query(WebhookLog).filter(
        WebhookLog.instance_id == instance_id,
        WebhookLog.status == "completed",
        WebhookLog.created_at < cutoff_date
    ).delete()
    db.commit()
    
    return {
        "message": f"Se eliminaron {deleted} logs de webhooks",
        "cutoff_date": cutoff_date.isoformat(),
        "days": days
    }


@router.get("/tasks", response_model=List[TaskLogResponse])
async def get_task_logs(
    status: Optional[str] = Query(None, description="Filtrar por status: pending, started, retry, success, failure"),
    task_name: Optional[str] = Query(None, description="Filtrar por nombre de tarea"),
    limit: int = Query(100, le=1000, description="Límite de resultados"),
    skip: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener logs de tareas Celery ejecutadas.
    
    Permite filtrar por status, nombre de tarea y paginación.
    """
    instance_id = get_active_instance_id(db, current_user)
    task_log_repo = TaskLogRepository(db)
    
    logs = task_log_repo.get_task_logs(
        instance_id=instance_id,
        limit=limit,
        offset=skip,
        status=status,
        task_name=task_name
    )
    
    return logs


@router.get("/tasks/{task_id}", response_model=TaskLogResponse)
async def get_task_log(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener un log de tarea específico por su ID.
    Solo permite acceso a tareas de la instancia activa del usuario.
    """
    instance_id = get_active_instance_id(db, current_user)
    task_log_repo = TaskLogRepository(db)
    log = task_log_repo.get_task_log(task_id)
    
    if not log:
        raise HTTPException(status_code=404, detail=f"Task log {task_id} no encontrado")
    
    # Verificar que la tarea pertenece a la instancia del usuario
    if log.instance_id != instance_id:
        raise HTTPException(status_code=404, detail=f"Task log {task_id} no encontrado")
    
    return log


@router.get("/products", response_model=List[ProductSyncResponse])
async def get_product_syncs(
    has_error: Optional[bool] = Query(None, description="Filtrar por productos con error"),
    limit: int = Query(100, le=1000, description="Límite de resultados"),
    skip: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registros de sincronización de productos.
    
    Permite filtrar por productos con errores.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = ProductSyncRepository(db)
    
    syncs = sync_repo.get_syncs(
        instance_id=instance_id,
        error=has_error,
        limit=limit,
        offset=skip
    )
    
    return syncs


@router.get("/products/odoo/{odoo_id}", response_model=ProductSyncResponse)
async def get_product_sync_by_odoo_id(
    odoo_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registro de sincronización de producto por su ID de Odoo.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = ProductSyncRepository(db)
    sync = sync_repo.get_sync_by_odoo_id(odoo_id, instance_id)
    
    if not sync:
        raise HTTPException(status_code=404, detail=f"Product sync con odoo_id={odoo_id} no encontrado")
    
    return sync


@router.get("/products/woocommerce/{wc_id}", response_model=ProductSyncResponse)
async def get_product_sync_by_wc_id(
    wc_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registro de sincronización de producto por su ID de WooCommerce.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = ProductSyncRepository(db)
    sync = sync_repo.get_product_sync_by_wc_id(wc_id, instance_id)
    
    if not sync:
        raise HTTPException(status_code=404, detail=f"Product sync con woocommerce_id={wc_id} no encontrado")
    
    return sync


@router.get("/categories", response_model=List[CategorySyncResponse])
async def get_category_syncs(
    has_error: Optional[bool] = Query(None, description="Filtrar por categorías con error"),
    limit: int = Query(100, le=1000, description="Límite de resultados"),
    skip: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registros de sincronización de categorías.
    
    Permite filtrar por categorías con errores.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = CategorySyncRepository(db)
    
    syncs = sync_repo.get_syncs(
        instance_id=instance_id,
        error=has_error,
        limit=limit,
        offset=skip
    )
    
    return syncs


@router.get("/categories/odoo/{odoo_id}", response_model=CategorySyncResponse)
async def get_category_sync_by_odoo_id(
    odoo_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registro de sincronización de categoría por su ID de Odoo.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = CategorySyncRepository(db)
    sync = sync_repo.get_sync_by_odoo_id(odoo_id, instance_id)
    
    if not sync:
        raise HTTPException(status_code=404, detail=f"Category sync con odoo_id={odoo_id} no encontrado")
    
    return sync


@router.get("/tags", response_model=List[TagSyncResponse])
async def get_tag_syncs(
    has_error: Optional[bool] = Query(None, description="Filtrar por tags con error"),
    limit: int = Query(100, le=1000, description="Límite de resultados"),
    skip: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registros de sincronización de tags.
    
    Permite filtrar por tags con errores.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = TagSyncRepository(db)
    
    syncs = sync_repo.get_syncs(
        instance_id=instance_id,
        error=has_error,
        limit=limit,
        offset=skip
    )
    
    return syncs


@router.get("/tags/odoo/{odoo_id}", response_model=TagSyncResponse)
async def get_tag_sync_by_odoo_id(
    odoo_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener registro de sincronización de tag por su ID de Odoo.
    """
    instance_id = get_active_instance_id(db, current_user)
    sync_repo = TagSyncRepository(db)
    sync = sync_repo.get_sync_by_odoo_id(odoo_id, instance_id)
    
    if not sync:
        raise HTTPException(status_code=404, detail=f"Tag sync con odoo_id={odoo_id} no encontrado")
    
    return sync


@router.get("/statistics", response_model=SyncStatisticsResponse)
async def get_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener estadísticas agregadas de sincronización.
    
    Incluye totales y breakdowns por status de webhooks, tareas, productos y categorías.
    """
    instance_id = get_active_instance_id(db, current_user)
    product_repo = ProductSyncRepository(db)
    category_repo = CategorySyncRepository(db)
    tag_repo = TagSyncRepository(db)
    webhook_repo = WebhookRepository(db)
    
    webhook_stats = webhook_repo.get_webhook_statistics(instance_id=instance_id)
    product_stats = product_repo.get_product_sync_statistics(instance_id=instance_id)
    category_stats = category_repo.get_sync_stats(instance_id=instance_id)
    tag_stats = tag_repo.get_sync_stats(instance_id=instance_id)
    
    return SyncStatisticsResponse(
        webhooks=webhook_stats,
        tasks={"total": 0},  # Task stats don't have a specific method yet
        products=product_stats,
        categories=category_stats
    )
