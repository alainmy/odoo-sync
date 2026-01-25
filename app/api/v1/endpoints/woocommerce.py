from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.models.product_models import (
    OdooProduct,
    OdooToWooCommerceRequest,
    OdooToWooCommerceSyncResponse,
    ProductSyncResult,
    WooCommerceProductCreate,
    OdooCategory,
    CategorySyncResult,
    OdooCategoriesToWooCommerceRequest,
    OdooCategoriesToWooCommerceSyncResponse,
    WooCommerceCategoryCreate
)
import os
import requests
import uuid
import time
import logging
from decimal import Decimal
from app.core.config import settings
from app.schemas.schemas import TASKS, BulkSyncRequest, \
    BulkSyncResponse, Product, SyncResult
from app.services.woocommerce import background_full_sync, \
    create_or_update_woocommerce_category, \
    create_or_update_woocommerce_product, \
    fetch_wc_product, odoo_product_to_woocommerce, \
    push_to_odoo, wc_request
from app.crud.category_sync import get_categories_map
from app.db.session import get_db
from app.repositories import ProductSyncRepository, CategorySyncRepository
from app.schemas.admin import CategorySyncCreate, ProductSyncCreate
router = APIRouter(prefix="/woocommerce", tags=["woocommerce"])

_logger = logging.getLogger(__name__)


@router.get("/products", response_model=List[Product])
def list_products(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), status: Optional[str] = None):
    params = {"page": page, "per_page": per_page}
    if status:
        params["status"] = status
    data = wc_request("GET", "products", params=params)
    return [
        Product(
            id=p["id"],
            name=p.get("name"),
            sku=p.get("sku"),
            price=p.get("price"),
            status=p.get("status"),
            type=p.get("type"),
        )
        for p in data
    ]


@router.post("/products/sync/{product_id}", response_model=SyncResult)
def sync_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    product = fetch_wc_product(product_id)
    ok = push_to_odoo(product)
    return SyncResult(product_id=product_id, synced=ok, detail="Synced" if ok else "Failed")


@router.post("/products/sync", response_model=BulkSyncResponse)
def bulk_sync(
    body: BulkSyncRequest,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    results: List[SyncResult] = []
    for pid in body.product_ids:
        try:
            product = fetch_wc_product(pid)
            ok = push_to_odoo(product)
            results.append(SyncResult(product_id=pid, synced=ok,
                           detail="Synced" if ok else "Failed"))
        except HTTPException as e:
            results.append(SyncResult(
                product_id=pid, synced=False, detail=str(e.detail)))
    return BulkSyncResponse(results=results)


@router.post("/products/full-sync")
def full_sync(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"status": "queued", "processed": 0}
    background.add_task(background_full_sync(task_id))
    return {"task_id": task_id, "status": "queued"}


@router.get("/sync/status/{task_id}")
def sync_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/products/sync-from-odoo",
             response_model=OdooToWooCommerceSyncResponse)
async def sync_products_from_odoo(request: OdooToWooCommerceRequest,
                            db: Session = Depends(get_db)):
    """
    Sincroniza productos desde Odoo hacia WooCommerce

    Este endpoint recibe una lista de productos en formato Odoo y los
    crea/actualiza en WooCommerce según la configuración especificada.
    """
    start_time = time.time()

    results = []
    counters = {
        "successful": 0,
        "failed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0
    }

    for odoo_product in request.products:
        # Convertir producto Odoo a formato WooCommerce
        wc_product_data = await odoo_product_to_woocommerce(
            odoo_product,
            request.default_status
        )

        # Sincronizar producto
        sync_result = await create_or_update_woocommerce_product(
            odoo_product=odoo_product,
            wc_product_data=wc_product_data,
            create_if_not_exists=request.create_if_not_exists,
            update_existing=request.update_existing,
            db=db
        )

        results.append(sync_result)

        # Actualizar contadores
        if sync_result.success:
            counters["successful"] += 1
            counters[sync_result.action] += 1

            # Guardar mapeo Odoo ID -> WooCommerce ID usando ProductSyncRepository
            if sync_result.woocommerce_id and odoo_product.id:
                sync_repo = ProductSyncRepository(db)
                existing_sync = sync_repo.get_sync_by_odoo_id(odoo_product.id, instance_id)
                
                if existing_sync:
                    # Actualizar registro existente
                    sync_repo.update_sync(
                        sync_id=existing_sync.id,
                        woocommerce_id=sync_result.woocommerce_id,
                        created=sync_result.action == "created",
                        updated=sync_result.action == "updated",
                        skipped=sync_result.action == "skipped",
                        error=False,
                        message=sync_result.message
                    )
                else:
                    # Crear nuevo registro
                    sync_repo.create_product_sync(
                        odoo_id=odoo_product.id,
                        woocommerce_id=sync_result.woocommerce_id,
                        created=sync_result.action == "created",
                        updated=sync_result.action == "updated",
                        skipped=sync_result.action == "skipped",
                        error=False,
                        message=sync_result.message
                    )
        else:
            counters["failed"] += 1
            
            # Registrar error en ProductSync
            if odoo_product.id:
                sync_repo = ProductSyncRepository(db)
                existing_sync = sync_repo.get_sync_by_odoo_id(odoo_product.id, instance_id)
                
                if existing_sync:
                    sync_repo.update_sync(
                        sync_id=existing_sync.id,
                        error=True,
                        message=sync_result.message,
                        error_details=sync_result.error_details
                    )
                else:
                    sync_repo.create_product_sync(
                        odoo_id=odoo_product.id,
                        woocommerce_id=sync_result.woocommerce_id or 0,
                        error=True,
                        message=sync_result.message,
                        error_details=sync_result.error_details
                    )

    end_time = time.time()

    return OdooToWooCommerceSyncResponse(
        total_products=len(request.products),
        successful=counters["successful"],
        failed=counters["failed"],
        created=counters["created"],
        updated=counters["updated"],
        skipped=counters["skipped"],
        results=results,
        sync_duration_seconds=round(end_time - start_time, 2)
    )


@router.post("/categories/sync-from-odoo",
             response_model=OdooCategoriesToWooCommerceSyncResponse)
async def sync_categories_from_odoo(
    request: OdooCategoriesToWooCommerceRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Sincroniza categorías desde Odoo hacia WooCommerce

    Este endpoint recibe una lista de categorías en formato Odoo y las
    crea/actualiza en WooCommerce. Si create_hierarchy está activado,
    procesará primero las categorías padre.
    """
    from app.crud import instance as crud_instance
    
    # Obtener instancia activa
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No hay ninguna instancia activa. Por favor activa una instancia."
        )
    instance_id = instance.id
    
    start_time = time.time()

    results = []
    counters = {
        "successful": 0,
        "failed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0
    }

    # Mapa para trackear IDs: Odoo ID -> WooCommerce ID
    categories_map = get_categories_map(db)

    # Si se necesita jerarquía, ordenar categorías (padres primero)
    categories_to_process = request.categories
    if request.create_hierarchy:
        # Separar categorías sin padre (raíz) y con padre
        root_categories = [
            cat for cat in categories_to_process if not cat.parent_id
        ]
        child_categories = [
            cat for cat in categories_to_process if cat.parent_id
        ]
        # Procesar primero las raíz, luego las hijas
        categories_to_process = root_categories + child_categories

    for odoo_category in categories_to_process:
        # Crear datos para WooCommerce
        wc_category_data = WooCommerceCategoryCreate(
            name=odoo_category.name,
            description=odoo_category.description,
            slug=None  # WooCommerce generará el slug automáticamente
        )

        # Sincronizar categoría
        sync_result = await create_or_update_woocommerce_category(
            odoo_category=odoo_category,
            wc_category_data=wc_category_data,
            create_if_not_exists=request.create_if_not_exists,
            update_existing=request.update_existing,
            categories_map=categories_map
        )

        results.append(sync_result)

        # Actualizar contadores
        if sync_result.success:
            counters["successful"] += 1
            counters[sync_result.action] += 1

            # Guardar mapeo Odoo ID -> WooCommerce ID usando CategorySyncRepository
            if sync_result.woocommerce_id:
                categories_map[odoo_category.id] = sync_result.woocommerce_id
                sync_repo = CategorySyncRepository(db)
                existing_sync = sync_repo.get_sync_by_odoo_id(odoo_category.id, instance_id)
                
                if existing_sync:
                    # Actualizar registro existente
                    sync_repo.update_sync(
                        sync_id=existing_sync.id,
                        woocommerce_id=sync_result.woocommerce_id,
                        created=sync_result.action == "created",
                        updated=sync_result.action == "updated",
                        skipped=sync_result.action == "skipped",
                        error=False,
                        message=sync_result.message
                    )
                else:
                    # Crear nuevo registro
                    sync_repo.create_category_sync(
                        odoo_id=odoo_category.id,
                        woocommerce_id=sync_result.woocommerce_id,
                        instance_id=instance_id,
                        created=sync_result.action == "created",
                        updated=sync_result.action == "updated",
                        skipped=sync_result.action == "skipped",
                        error=False,
                        message=sync_result.message
                    )
        else:
            counters["failed"] += 1
            
            # Registrar error en CategorySync
            sync_repo = CategorySyncRepository(db)
            existing_sync = sync_repo.get_sync_by_odoo_id(odoo_category.id, instance_id)
            
            if existing_sync:
                sync_repo.update_sync(
                    sync_id=existing_sync.id,
                    error=True,
                    message=sync_result.message,
                    error_details=sync_result.error_details
                )
            else:
                sync_repo.create_category_sync(
                    odoo_id=odoo_category.id,
                    woocommerce_id=sync_result.woocommerce_id or 0,
                    instance_id=instance_id,
                    error=True,
                    message=sync_result.message,
                    error_details=sync_result.error_details
                )

    end_time = time.time()

    return OdooCategoriesToWooCommerceSyncResponse(
        total_categories=len(request.categories),
        successful=counters["successful"],
        failed=counters["failed"],
        created=counters["created"],
        updated=counters["updated"],
        skipped=counters["skipped"],
        results=results,
        sync_duration_seconds=round(end_time - start_time, 2)
    )
