"""
Endpoints para sincronización de atributos Odoo ↔ WooCommerce

Endpoints:
- POST /attributes/sync-from-odoo - Sincronizar atributos desde Odoo a WooCommerce (async con Celery)
- POST /attributes/sync-from-odoo/immediate - Sincronización inmediata (sin Celery)
- GET /attributes/syncs - Listar sincronizaciones de atributos
- GET /attributes/syncs/{odoo_id} - Ver estado de sincronización específica
- GET /attributes/statistics - Estadísticas de sincronización
"""
import time
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.crud import instance as crud_instance
from app.repositories.attribute_repository import AttributeSyncRepository
from app.services.woocommerce_attributes import (
    create_or_update_woocommerce_attribute,
    sync_attribute_values,
    get_woocommerce_attributes,
    get_woocommerce_attribute_terms
)
from app.services.odoo_attributes import (
    get_odoo_attributes,
    get_odoo_attribute_by_id
)
from app.services.odoo_service import OdooClient
from app.schemas.attributes import (
    AttributeSyncRequest,
    AttributeSyncResponse,
    AttributeSyncResult,
    AttributeSyncStatus,
    AttributeValueSyncStatus,
    OdooAttribute,
    AttributeSyncStatusResponse,
    AttributeListResponse,
    AttributeBatchSyncRequest,
    AttributeBatchSyncResponse,
    AttributeSyncStatsResponse
)
from app.tasks.attribute_tasks import (
    sync_attributes_from_odoo as sync_attributes_task,
    sync_single_attribute as sync_single_attribute_task
)
from app.utils.instance_helpers import get_active_instance_id, get_instance_configs
from celery.result import AsyncResult
from celery import group

router = APIRouter(prefix="/attributes", tags=["attributes"])
_logger = logging.getLogger(__name__)


@router.post("/sync-from-odoo")
async def sync_attributes_from_odoo(
    request: AttributeSyncRequest,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Sincronizar atributos desde Odoo hacia WooCommerce (asíncrono con Celery)
    
    Esta tarea se ejecuta en background usando Celery.
    
    Args:
        request: Lista de atributos de Odoo con configuración de sync
        
    Returns:
        ID de la tarea de Celery para seguimiento
    """
    # Obtener instancia activa
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa. Por favor activa una instancia."
        )
    
    # Extraer IDs de los atributos a sincronizar
    attribute_ids = [attr.id for attr in request.attributes]
    
    # Lanzar tarea de Celery
    task = sync_attributes_task.apply_async(
        kwargs={
            "instance_id": instance.id,
            "attribute_ids": attribute_ids,
            "create_if_not_exists": request.create_if_not_exists,
            "update_existing": request.update_existing
        }
    )
    
    _logger.info(
        f"Attribute sync task launched: {task.id} for {len(attribute_ids)} attributes"
    )
    
    return {
        "task_id": task.id,
        "status": "pending",
        "message": f"Sincronización de {len(attribute_ids)} atributos iniciada",
        "attributes_count": len(attribute_ids)
    }


@router.post("/sync-from-odoo/immediate", response_model=AttributeSyncResponse)
async def sync_attributes_from_odoo_immediate(
    request: AttributeSyncRequest,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Sincronizar atributos desde Odoo hacia WooCommerce (inmediato, sin Celery)
    
    Útil para testing o sincronización de pocos atributos.
    Para grandes volúmenes usar el endpoint sin /immediate que usa Celery.
    
    Flujo:
    1. Recibe lista de atributos desde Odoo (con sus valores)
    2. Crea/actualiza cada atributo en WooCommerce
    3. Sincroniza los valores (terms) de cada atributo
    4. Guarda mapeo en AttributeSync y AttributeValueSync
    
    Args:
        request: Lista de atributos de Odoo con configuración de sync
        
    Returns:
        Respuesta con resultados de sincronización
    """
    # Obtener instancia activa
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa. Por favor activa una instancia."
        )
    
    start_time = time.time()
    results = []
    counters = {
        "successful": 0,
        "failed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0
    }
    
    _logger.info(f"Starting attribute sync for {len(request.attributes)} attributes")
    
    for odoo_attribute in request.attributes:
        try:
            # 1. Sincronizar atributo
            attribute_result = await create_or_update_woocommerce_attribute(
                odoo_attribute=odoo_attribute,
                instance_id=instance.id,
                db=db,
                create_if_not_exists=request.create_if_not_exists,
                update_existing=request.update_existing
            )
            
            # 2. Sincronizar valores si está habilitado y el atributo se creó/actualizó exitosamente
            values_synced = 0
            if request.sync_values and attribute_result.woocommerce_id and attribute_result.success:
                value_results = await sync_attribute_values(
                    odoo_attribute=odoo_attribute,
                    woocommerce_attribute_id=attribute_result.woocommerce_id,
                    instance_id=instance.id,
                    db=db,
                    create_if_not_exists=request.create_if_not_exists,
                    update_existing=request.update_existing
                )
                
                # Contar valores exitosos
                values_synced = sum(1 for v in value_results if v.success)
                attribute_result.values_synced = values_synced
                
                _logger.info(
                    f"Attribute '{odoo_attribute.name}': "
                    f"{values_synced}/{len(value_results)} values synced"
                )
            
            results.append(attribute_result)
            
            # Actualizar contadores
            if attribute_result.success:
                counters["successful"] += 1
                counters[attribute_result.action] += 1
            else:
                counters["failed"] += 1
                
        except Exception as e:
            _logger.error(f"Error syncing attribute {odoo_attribute.id}: {e}")
            results.append(AttributeSyncResult(
                odoo_id=odoo_attribute.id,
                odoo_name=odoo_attribute.name,
                woocommerce_id=None,
                success=False,
                action="error",
                message=str(e),
                error_details=str(e),
                values_synced=0
            ))
            counters["failed"] += 1
    
    end_time = time.time()
    
    return AttributeSyncResponse(
        total_processed=len(request.attributes),
        successful=counters["successful"],
        failed=counters["failed"],
        created=counters["created"],
        updated=counters["updated"],
        skipped=counters["skipped"],
        results=results,
        sync_duration_seconds=round(end_time - start_time, 2)
    )


@router.get("/task/{task_id}")
async def get_attribute_sync_task_status(
    task_id: str,
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener estado de una tarea de sincronización de atributos
    
    Args:
        task_id: ID de la tarea de Celery
        
    Returns:
        Estado actual de la tarea
    """
    task_result = AsyncResult(task_id)
    
    response = {
        "task_id": task_id,
        "status": task_result.status,
        "ready": task_result.ready(),
        "successful": task_result.successful() if task_result.ready() else None,
    }
    
    if task_result.ready():
        if task_result.successful():
            response["result"] = task_result.result
        else:
            response["error"] = str(task_result.info)
    
    return response


@router.get("/syncs", response_model=List[AttributeSyncStatus])
async def get_attribute_syncs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Listar todas las sincronizaciones de atributos
    
    Returns:
        Lista de sincronizaciones con su estado
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    repo = AttributeSyncRepository(db)
    syncs = repo.get_attribute_syncs(
        instance_id=instance.id,
        skip=skip,
        limit=limit
    )
    
    return [
        AttributeSyncStatus(
            id=sync.id,
            odoo_attribute_id=sync.odoo_attribute_id,
            attribute_name=None,  # Se podría obtener de Odoo si es necesario
            woocommerce_id=sync.woocommerce_id,
            slug=sync.slug,
            created=sync.created,
            updated=sync.updated,
            skipped=sync.skipped,
            error=sync.error,
            message=sync.message,
            sync_date=sync.sync_date,
            last_exported_date=sync.last_exported_date,
            need_update=sync.need_update
        )
        for sync in syncs
    ]


@router.get("/syncs/{odoo_attribute_id}", response_model=AttributeSyncStatus)
async def get_attribute_sync(
    odoo_attribute_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener estado de sincronización de un atributo específico
    
    Args:
        odoo_attribute_id: ID del atributo en Odoo
        
    Returns:
        Estado de sincronización
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    repo = AttributeSyncRepository(db)
    sync = repo.get_attribute_sync_by_odoo_id(odoo_attribute_id, instance.id)
    
    if not sync:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró sincronización para el atributo Odoo ID {odoo_attribute_id}"
        )
    
    return AttributeSyncStatus(
        id=sync.id,
        odoo_attribute_id=sync.odoo_attribute_id,
        attribute_name=None,
        woocommerce_id=sync.woocommerce_id,
        slug=sync.slug,
        created=sync.created,
        updated=sync.updated,
        skipped=sync.skipped,
        error=sync.error,
        message=sync.message,
        sync_date=sync.sync_date,
        last_exported_date=sync.last_exported_date,
        need_update=sync.need_update
    )


@router.get("/syncs/{odoo_attribute_id}/values", response_model=List[AttributeValueSyncStatus])
async def get_attribute_value_syncs(
    odoo_attribute_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener sincronizaciones de valores de un atributo
    
    Args:
        odoo_attribute_id: ID del atributo en Odoo
        
    Returns:
        Lista de valores sincronizados
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    repo = AttributeSyncRepository(db)
    
    # Primero obtener el sync del atributo
    attribute_sync = repo.get_attribute_sync_by_odoo_id(odoo_attribute_id, instance.id)
    if not attribute_sync or not attribute_sync.woocommerce_id:
        raise HTTPException(
            status_code=404,
            detail=f"Atributo Odoo ID {odoo_attribute_id} no está sincronizado con WooCommerce"
        )
    
    # Obtener valores sincronizados
    value_syncs = repo.get_attribute_value_syncs_by_attribute(
        woocommerce_attribute_id=attribute_sync.woocommerce_id,
        instance_id=instance.id
    )
    
    return [
        AttributeValueSyncStatus(
            id=sync.id,
            odoo_value_id=sync.odoo_value_id,
            value_name=None,  # Se podría obtener de Odoo
            woocommerce_id=sync.woocommerce_id,
            woocommerce_attribute_id=sync.woocommerce_attribute_id,
            slug=sync.slug,
            created=sync.created,
            updated=sync.updated,
            error=sync.error,
            message=sync.message,
            sync_date=sync.sync_date
        )
        for sync in value_syncs
    ]


@router.get("/statistics")
async def get_attribute_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Obtener estadísticas de sincronización de atributos
    
    Returns:
        Estadísticas globales
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    repo = AttributeSyncRepository(db)
    stats = repo.get_sync_statistics(instance.id)
    
    return {
        "instance_id": instance.id,
        "instance_name": instance.name,
        **stats
    }


@router.get("/woocommerce/list")
async def list_woocommerce_attributes(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Listar atributos directamente desde WooCommerce
    
    Útil para debugging y verificación
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    attributes = await get_woocommerce_attributes(
        instance_id=instance.id,
        page=page,
        per_page=per_page
    )
    
    return {
        "total": len(attributes),
        "page": page,
        "per_page": per_page,
        "attributes": attributes
    }


@router.get("/woocommerce/{attribute_id}/terms")
async def list_woocommerce_attribute_terms(
    attribute_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Listar terms de un atributo desde WooCommerce
    
    Args:
        attribute_id: ID del atributo en WooCommerce
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    terms = await get_woocommerce_attribute_terms(
        attribute_id=attribute_id,
        page=page,
        per_page=per_page
    )
    
    return {
        "attribute_id": attribute_id,
        "total": len(terms),
        "page": page,
        "per_page": per_page,
        "terms": terms
    }


@router.get("/odoo/list", response_model=List[OdooAttribute])
async def list_odoo_attributes(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    name_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Listar atributos disponibles en Odoo
    
    Args:
        limit: Cantidad máxima de atributos a retornar
        offset: Offset para paginación
        name_filter: Filtro opcional por nombre
    
    Returns:
        Lista de atributos de Odoo con sus valores
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa"
        )
    
    # Conectar a Odoo
    odoo_client = OdooClient(
        url=instance.odoo_url,
        db=instance.odoo_db,
        username=instance.odoo_username,
        password=instance.odoo_password
    )
    
    uid = await odoo_client.odoo_authenticate()
    if not uid:
        raise HTTPException(
            status_code=401,
            detail="No se pudo autenticar con Odoo"
        )
    
    # Obtener atributos de Odoo
    try:
        attributes = await get_odoo_attributes(
            odoo_client=odoo_client,
            limit=limit,
            offset=offset,
            name_filter=name_filter
        )
        return attributes
    except Exception as e:
        _logger.error(f"Error obteniendo atributos de Odoo: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo atributos de Odoo: {str(e)}"
        )


# ==================== ATTRIBUTE MANAGEMENT ENDPOINTS ====================

# Create a second router for attribute management
management_router = APIRouter(prefix="/attribute-management", tags=["Attribute Management"])


@management_router.get("/attributes", response_model=AttributeListResponse)
async def list_odoo_attributes_with_sync_status(
    limit: int = Query(50, le=200, description="Number of attributes to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    filter_status: Optional[str] = Query(
        None,
        description="Filter by sync status: never_synced, synced, error"
    ),
    search: Optional[str] = Query(None, description="Search by attribute name"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    List Odoo attributes with their WooCommerce sync status.
    """
    try:
        # Get active instance
        instance = crud_instance.get_active_instance(db, user_id=current_user.id)
        if not instance:
            raise HTTPException(
                status_code=404,
                detail="No hay ninguna instancia activa. Por favor activa una instancia."
            )

        # Connect to Odoo
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )

        # Authenticate with Odoo
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="No se pudo autenticar con Odoo"
            )

        # Build Odoo domain for filtering
        domain = []
        if search:
            domain.append(["name", "ilike", search])

        _logger.info(f"Fetching attributes from Odoo: domain={domain}, limit={limit}")

        # Fetch from Odoo
        odoo_response = await odoo_client.search_read(
            uid,
            "product.attribute",
            domain=domain if domain else [],
            fields=["id", "name", "display_name", "display_type", "create_variant"],
            limit=limit,
            offset=offset
        )

        odoo_attributes = odoo_response.get("result", [])
        _logger.info(f"Fetched {len(odoo_attributes)} attributes from Odoo")

        # Get sync repository
        sync_repo = AttributeSyncRepository(db)
        enriched_attributes = []

        for attr in odoo_attributes:
            # Get attribute values with complete data
            values_response = await odoo_client.search_read(
                uid,
                "product.attribute.value",
                domain=[["attribute_id", "=", attr["id"]]],
                fields=["id", "name", "display_name", "html_color", "display_type"],
                limit=1000
            )
            values_data = values_response.get("result", [])
            value_count = len(values_data)
            
            # Convert values to OdooAttributeValue schema
            from app.schemas.attributes import OdooAttributeValue
            values = []
            for val in values_data:
                values.append(OdooAttributeValue(
                    id=val["id"],
                    name=val.get("name", ""),
                    display_name=val.get("display_name", val.get("name", "")),
                    html_color=val.get("html_color"),
                    display_type=val.get("display_type", "radio")
                ))

            # Get sync record
            sync_record = sync_repo.get_by_odoo_id(attr["id"], instance.id)

            # Calculate sync status
            if not sync_record:
                sync_status = "never_synced"
            elif sync_record.error:
                sync_status = "error"
            else:
                sync_status = "synced"

            # Apply filter
            if filter_status and sync_status != filter_status:
                continue

            enriched_attributes.append({
                "odoo_id": attr["id"],
                "name": attr.get("name", ""),
                "display_name": attr.get("display_name", attr.get("name", "")),
                "value_count": value_count,
                "values": values,
                "sync_status": sync_status,
                "woocommerce_id": sync_record.woocommerce_id if sync_record else None,
                "last_synced_at": sync_record.sync_date if sync_record else None,
                "has_error": sync_record.error if sync_record else False,
                "error_message": sync_record.message if sync_record and sync_record.error else None
            })

        _logger.info(f"Returning {len(enriched_attributes)} attributes after filtering")

        return AttributeListResponse(
            total_count=len(enriched_attributes),
            attributes=[AttributeSyncStatusResponse(**a) for a in enriched_attributes],
            filters_applied={
                "status": filter_status,
                "search": search,
                "limit": limit,
                "offset": offset
            }
        )

    except Exception as e:
        _logger.error(f"Error fetching attributes with sync status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching attributes: {str(e)}")


@management_router.post("/attributes/batch-sync", response_model=AttributeBatchSyncResponse)
async def batch_sync_attributes(
    request: AttributeBatchSyncRequest,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Queue multiple attributes for synchronization to WooCommerce.
    """
    try:
        # Get instance configurations
        instance = crud_instance.get_active_instance(
            db, user_id=current_user.id)
        odoo_config = {
            "url": instance.odoo_url,
            "db": instance.odoo_db,
            "username": instance.odoo_username,
            "password": instance.odoo_password
        }
        wc_config = {
            "url": instance.woocommerce_url,
            "consumer_key": instance.woocommerce_consumer_key,
            "consumer_secret": instance.woocommerce_consumer_secret
        }
        if not instance:
            raise HTTPException(
                status_code=404,
                detail="No hay ninguna instancia activa. Por favor activa una instancia."
            )

        # Connect to Odoo
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )

        # Authenticate with Odoo
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="No se pudo autenticar con Odoo"
            )

        # Fetch attribute data from Odoo
        odoo_response = await odoo_client.search_read(
            uid,
            "product.attribute",
            domain=[["id", "in", request.ids]],
            fields=["id", "name", "display_name", "display_type", "create_variant"]
        )

        attributes = odoo_response.get("result", [])

        if not attributes:
            raise HTTPException(
                status_code=404,
                detail=f"No attributes found with IDs: {request.ids}"
            )
        task_ids = []
        # Create task group for batch sync
        for attr in attributes:
            try:
                _logger.info(f"Queuing attribute {attr.get('id')}: {attr.get('name')}")
                task = sync_single_attribute_task.apply_async(
                    args=[instance.id, attr.get("id")],
                    kwargs={
                        "odoo_config": odoo_config,
                        "wc_config": wc_config
                    },
                    queue="sync_queue"
                )
                task_ids.append(str(task.id))
                _logger.info(f"Attribute {attr.get('id')} queued with task_id: {task.id}")
            except Exception as e:
                _logger.error(f"Error queuing attribute {attr.get('id')}: {e}", exc_info=True)

        # for attr in attributes:
            
        # task_group = group([
        #     sync_single_attribute_task.s(
        #         instance_id=instance.id,
        #         odoo_attribute_id=attr["id"]
        #     )
        #     for attr in attributes
        # ])

        # Execute task group

        _logger.info(f"Queued {len(task_ids)} attributes for sync")

        return AttributeBatchSyncResponse(
            total=len(request.ids),
            queued=len(task_ids),
            task_ids=task_ids,
            message=f"Successfully queued {len(task_ids)} attributes for synchronization"
        )

    except Exception as e:
        _logger.error(f"Error batch syncing attributes: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error syncing attributes: {str(e)}")


@management_router.get("/attributes/statistics", response_model=AttributeSyncStatsResponse)
async def get_attribute_sync_statistics(
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """
    Get attribute sync statistics including total from Odoo.
    """
    try:
        # Get active instance
        instance = crud_instance.get_active_instance(db, user_id=current_user.id)
        if not instance:
            raise HTTPException(
                status_code=404,
                detail="No hay ninguna instancia activa"
            )

        # Connect to Odoo
        odoo_client = OdooClient(
            url=instance.odoo_url,
            db=instance.odoo_db,
            username=instance.odoo_username,
            password=instance.odoo_password
        )

        # Authenticate with Odoo
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="No se pudo autenticar con Odoo"
            )

        # Get total count from Odoo using search (returns only IDs)
        search_response = await odoo_client.search_read(
            uid,
            "product.attribute",
            domain=[],
            fields=["id"],
            limit=10000,  # High limit to get all
            offset=0
        )
        total_in_odoo = len(search_response.get("result", []))

        # Get sync stats from DB
        sync_repo = AttributeSyncRepository(db)
        stats = sync_repo.get_sync_statistics(instance.id)

        # Calculate synced (attributes that have woocommerce_id)
        synced_count = sync_repo.count_synced(instance.id)
        error_count = sync_repo.count_errors(instance.id)

        return AttributeSyncStatsResponse(
            total=total_in_odoo,
            synced=synced_count,
            never_synced=total_in_odoo - synced_count,
            errors=error_count
        )

    except Exception as e:
        _logger.error(f"Error getting attribute statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

