"""
Servicio para sincronización de atributos Odoo ↔ WooCommerce

Flujo:
1. Leer atributos de Odoo (product.attribute + product.attribute.value)
2. Crear/actualizar en WooCommerce (attributes + terms)
3. Guardar mapeo en AttributeSync + AttributeValueSync
"""
import logging
from typing import Dict, Optional, List
from sqlalchemy.engine import create
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.woocommerce import wc_request, wc_request_with_logging
from app.schemas.attributes import (
    OdooAttribute,
    OdooAttributeValue,
    WooCommerceAttribute,
    WooCommerceAttributeTerm,
    AttributeSyncResult,
    AttributeValueSyncResult
)
from app.repositories.attribute_repository import AttributeSyncRepository
from woocommerce import API
_logger = logging.getLogger(__name__)


async def get_attribute_by_id(
    wc_attribute_id: int,
    wcapi: API = None
) -> Optional[Dict]:
    """
    Obtener un atributo de WooCommerce por ID

    Args:
        wc_attribute_id: ID del atributo en WooCommerce
        wcapi: Cliente API de WooCommerce

    Returns:
        Diccionario del atributo si se encuentra, None si no
    """
    try:
        attr = wc_request_with_logging(
            "GET", f"products/attributes/{wc_attribute_id}", wcapi=wcapi)
        if isinstance(attr, dict):
            return attr
        return None
    except Exception as e:
        _logger.error(
            f"Error fetching WooCommerce attribute ID {wc_attribute_id}: {e}")
        return None


async def get_attribute_terms_by_id(
    wc_attribute_id: int,
    existing_sync_woocommerce_id: int = None,
    wcapi: API = None
) -> List[Dict]:
    """
    Obtener términos (terms) de un atributo de WooCommerce por ID

    Args:
        wc_attribute_id: ID del atributo en WooCommerce
        wcapi: Cliente API de WooCommerce

    Returns:
        Lista de términos del atributo
    """
    try:
        terms = wc_request_with_logging(
            "GET", f"products/attributes/{wc_attribute_id}/terms/{existing_sync_woocommerce_id}", wcapi=wcapi)
        if isinstance(terms, dict):
            return terms
        return None
    except Exception as e:
        _logger.error(
            f"Error fetching WooCommerce attribute terms for ID {wc_attribute_id}: {e}")
        return None


async def get_attribute_terms_by_slug(
    wc_attribute_id: int,
    slug: str,
    wcapi: API = None
) -> Optional[Dict]:
    """
    Obtener un término (term) de un atributo de WooCommerce por slug

    Args:
        wc_attribute_id: ID del atributo en WooCommerce
        slug: Slug del término
        wcapi: Cliente API de WooCommerce

    Returns:
        Diccionario del término si se encuentra, None si no
    """
    try:
        terms = wc_request_with_logging(
            "GET",
            f"products/attributes/{wc_attribute_id}/terms",
            params={"slug": slug, "per_page": 1},
            wcapi=wcapi
        )
        for term in terms:
            if term.get("slug") == slug:
                return term
        return None
    except Exception as e:
        _logger.error(
            f"Error fetching WooCommerce attribute term by slug '{slug}' for attribute ID {wc_attribute_id}: {e}")
        return None


async def create_or_update_woocommerce_attribute(
    odoo_attribute: OdooAttribute,
    instance_id: int,
    db: Session,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    wcapi: API = None,
) -> AttributeSyncResult:
    """
    Crear o actualizar un atributo en WooCommerce

    Args:
        odoo_attribute: Atributo desde Odoo
        instance_id: ID de la instancia WooCommerce
        db: Sesión de base de datos
        create_if_not_exists: Crear si no existe
        update_existing: Actualizar si existe

    Returns:
        AttributeSyncResult con el resultado de la operación
    """
    repo = AttributeSyncRepository(db)
    action = "skipped"
    message = "Not processed"
    woocommerce_id = None

    try:
        # 1. Buscar sync existente en BD
        existing_sync = repo.get_attribute_sync_by_odoo_id(
            odoo_attribute.id,
            instance_id
        )
        _logger.info(f"Existing sync record: {existing_sync}")
        # 2. Buscar en WooCommerce (defensivo)
        # WooCommerce genera slug con prefijo 'pa_'
        slug_formated = odoo_attribute.name.lower().replace(" ", "-")
        _logger.info(f"Formatted slug for attribute: {slug_formated}")
        slug = 'pa_' + slug_formated
        _logger.info(f"Final slug for WooCommerce attribute: {slug}")
        original_slug = slug_formated  # Guardar para mensajes
        wc_attribute = None
        
        # Si existe sync, intentar buscar por ID guardado
        if existing_sync and existing_sync.woocommerce_id:
            try:
                wc_attribute = await get_attribute_by_id(existing_sync.woocommerce_id, wcapi=wcapi)
                _logger.info(f"Checking attribute existing: {wc_attribute}")
                if wc_attribute:
                    _logger.debug(f"Found attribute by sync ID: {existing_sync.woocommerce_id}")
            except Exception as e:
                _logger.warning(f"Attribute ID {existing_sync.woocommerce_id} not found in WC, will search by slug: {e}")
        _logger.info(f"WC Attribute after checking by ID: {wc_attribute}")
        # Si no se encontró por ID, buscar por slug
        if not wc_attribute:
            try:
                attrs = wc_request_with_logging(
                    "GET",
                    "products/attributes",
                    # params={"slug": slug, "per_page": 1},
                    wcapi=wcapi
                )
                _logger.info(f"Searching attribute by slug: {attrs}")
                for attr in attrs:
                    _logger.info(f"Checking attribute: {attr}")
                    if attr.get("slug") == slug:
                        wc_attribute = attr
                        _logger.debug(f"Found attribute by slug: {original_slug}")
                        break
            except Exception as e:
                _logger.debug(f"No attribute found by slug {original_slug}: {e}")
        
        # Extraer WC ID si se encontró
        if wc_attribute:
            woocommerce_id = wc_attribute.get("id")
            _logger.info(f"Attribute found: {wc_attribute}")
        
        # Preparar data para WooCommerce
        wc_data = {
            "name": odoo_attribute.name,
            "slug": slug,
            "type": "select",
            "order_by": "menu_order",
            "has_archives": False
        }
        
        # 3. Decidir acción: CREATE o UPDATE
        if woocommerce_id:
            # El atributo EXISTE en WooCommerce
            if update_existing:
                _logger.info(f"Updating attribute ID {woocommerce_id} in WooCommerce")
                wc_data.pop("slug", None)  # Asegurar que el slug se actualice si el nombre cambió
                update_response = wc_request_with_logging(
                    "PUT",
                    f"products/attributes/{woocommerce_id}",
                    params=wc_data,
                    wcapi=wcapi
                )
                
                if update_response and isinstance(update_response, dict) and "id" in update_response:
                    action = "updated"
                    message = f"Attribute updated successfully (ID {woocommerce_id})"
                    slug = update_response.get("slug", slug)
                    
                    # Actualizar o crear sync record
                    if existing_sync:
                        repo.update_attribute_sync(
                            existing_sync.id,
                            woocommerce_id=woocommerce_id,
                            slug=slug,
                            updated=True,
                            error=False,
                            message=message
                        )
                    else:
                        # Recuperación: crear sync record que faltaba
                        repo.create_attribute_sync(
                            instance_id=instance_id,
                            odoo_attribute_id=odoo_attribute.id,
                            odoo_name=odoo_attribute.name,
                            woocommerce_id=woocommerce_id,
                            slug=slug,
                            updated=True,
                            message=f"Sync record recovered: {message}"
                        )
                        _logger.info(f"Recovered missing sync record for attribute {odoo_attribute.id}")
                else:
                    action = "error"
                    message = f"Failed to update attribute: {update_response}"
                    _logger.error(message)
            else:
                action = "skipped"
                message = "Update disabled, attribute exists but not updated"
        else:
            # El atributo NO EXISTE en WooCommerce
            if create_if_not_exists:
                _logger.info(f"Creating attribute '{odoo_attribute.name}' in WooCommerce")
                create_response = wc_request_with_logging(
                    "POST",
                    "products/attributes",
                    params=wc_data,
                    wcapi=wcapi
                )
                
                if create_response and isinstance(create_response, dict) and "id" in create_response:
                    woocommerce_id = create_response["id"]
                    slug = create_response.get("slug", slug)
                    action = "created"
                    message = f"Attribute created successfully with ID {woocommerce_id}"
                    
                    # Actualizar o crear sync record
                    if existing_sync:
                        repo.update_attribute_sync(
                            existing_sync.id,
                            woocommerce_id=woocommerce_id,
                            slug=original_slug,
                            created=True,
                            error=False,
                            message=message
                        )
                    else:
                        repo.create_attribute_sync(
                            instance_id=instance_id,
                            odoo_attribute_id=odoo_attribute.id,
                            odoo_name=odoo_attribute.name,
                            woocommerce_id=woocommerce_id,
                            slug=original_slug,
                            created=True,
                            message=message
                        )
                else:
                    action = "error"
                    message = f"Failed to create attribute: {create_response}"
                    _logger.error(message)
            else:
                action = "skipped"
                message = "Create disabled, attribute not created"

        return AttributeSyncResult(
            odoo_id=odoo_attribute.id,
            odoo_name=odoo_attribute.name,
            woocommerce_id=woocommerce_id,
            success=(action in ["created", "updated", "skipped"]),
            action=action,
            message=message,
            values_synced=0  # Se actualizará después
        )

    except Exception as e:
        error_msg = f"Error syncing attribute {odoo_attribute.id}: {str(e)}"
        _logger.error(error_msg, exc_info=True)

        # Guardar error en sync
        if existing_sync:
            repo.update_attribute_sync(
                existing_sync.id,
                error=True,
                message=error_msg,
                error_details=str(e)
            )
        else:
            repo.create_attribute_sync(
                instance_id=instance_id,
                odoo_attribute_id=odoo_attribute.id,
                odoo_name=odoo_attribute.name,
                error=True,
                message=error_msg,
                error_details=str(e)
            )

        return AttributeSyncResult(
            odoo_id=odoo_attribute.id,
            odoo_name=odoo_attribute.name,
            woocommerce_id=None,
            success=False,
            action="error",
            message=error_msg,
            error_details=str(e),
            values_synced=0
        )


async def sync_attribute_values(
    odoo_attribute: OdooAttribute,
    woocommerce_attribute_id: int,
    instance_id: int,
    db: Session,
    create_if_not_exists: bool = True,
    update_existing: bool = True,
    wcapi: API = None,
) -> List[AttributeValueSyncResult]:
    """
    Sincronizar valores (terms) de un atributo

    Args:
        odoo_attribute: Atributo con sus valores
        woocommerce_attribute_id: ID del atributo en WooCommerce
        instance_id: ID de la instancia
        db: Sesión de base de datos

    Returns:
        Lista de resultados de sincronización
    """
    repo = AttributeSyncRepository(db)
    results = []

    for odoo_value in odoo_attribute.values:
        action = "skipped"
        message = "Not processed"
        woocommerce_term_id = None
        
        try:
            # 1. Buscar sync existente en BD
            existing_sync = repo.get_attribute_value_sync_by_odoo_id(
                odoo_value.id,
                instance_id
            )
            
            # 2. Buscar en WooCommerce (defensivo)
            slug = odoo_value.name.lower().replace(" ", "-")
            wc_term = None
            
            # Si existe sync, intentar buscar por ID guardado
            if existing_sync and existing_sync.woocommerce_id:
                try:
                    term = await get_attribute_terms_by_id(woocommerce_attribute_id,
                                                            existing_sync.woocommerce_id,
                                                            wcapi=wcapi)
                    # Buscar el term específico en la lista
                    wc_term = term
                    if wc_term:
                        _logger.info(f"Found term by sync ID: {existing_sync.woocommerce_id}")
                    else:
                        _logger.info(f"No se encontro el termino aqui")
                except Exception as e:
                    _logger.warning(f"Term ID {existing_sync.woocommerce_id} not found in WC, will search by slug: {e}")
            
            # Si no se encontró por ID, buscar por slug
            if not wc_term:
                wc_term = await get_attribute_terms_by_slug(
                    woocommerce_attribute_id,
                    slug=slug,
                    wcapi=wcapi
                )
                if wc_term:
                    _logger.debug(f"Found term by slug: {slug}")
                else:
                    _logger.info(f"Not found term by slug: {slug}")
            
            # Extraer WC ID si se encontró
            if wc_term:
                _logger.info(f"Term found: {wc_term}")
                woocommerce_term_id = wc_term.get("id")
            
            # Preparar data para WooCommerce
            wc_term_data = {
                "name": odoo_value.name,
                "slug": slug
            }
            
            # 3. Decidir acción: CREATE o UPDATE
            if woocommerce_term_id:
                # El term EXISTE en WooCommerce
                if update_existing:
                    _logger.info(f"Updating term ID {woocommerce_term_id} for attribute {woocommerce_attribute_id}")
                    update_response = wc_request_with_logging(
                        "PUT",
                        f"products/attributes/{woocommerce_attribute_id}/terms/{woocommerce_term_id}",
                        params=wc_term_data,
                        wcapi=wcapi
                    )
                    
                    if update_response and isinstance(update_response, dict) and "id" in update_response:
                        action = "updated"
                        message = f"Term updated successfully"
                        slug = update_response.get("slug", slug)
                        
                        # Actualizar o crear sync record
                        if existing_sync:
                            repo.update_attribute_value_sync(
                                existing_sync.id,
                                woocommerce_id=woocommerce_term_id,
                                woocommerce_attribute_id=woocommerce_attribute_id,
                                slug=slug,
                                updated=True,
                                error=False,
                                message=message
                            )
                        else:
                            # Recuperación: crear sync record que faltaba
                            repo.create_attribute_value_sync(
                                instance_id=instance_id,
                                odoo_value_id=odoo_value.id,
                                odoo_name=odoo_value.name,
                                woocommerce_id=woocommerce_term_id,
                                woocommerce_attribute_id=woocommerce_attribute_id,
                                slug=slug,
                                updated=True,
                                message=f"Sync record recovered: {message}"
                            )
                            _logger.info(f"Recovered missing sync record for value {odoo_value.id}")
                    else:
                        action = "error"
                        message = f"Failed to update term: {update_response}"
                else:
                    action = "skipped"
                    message = "Update disabled, term exists but not updated"
            else:
                # El term NO EXISTE en WooCommerce
                if create_if_not_exists:
                    _logger.info(f"Creating term '{odoo_value.name}' for attribute {woocommerce_attribute_id}")
                    create_response = wc_request_with_logging(
                        "POST",
                        f"products/attributes/{woocommerce_attribute_id}/terms",
                        params=wc_term_data,
                        wcapi=wcapi
                    )
                    
                    if create_response and isinstance(create_response, dict) and "id" in create_response:
                        woocommerce_term_id = create_response["id"]
                        slug = create_response.get("slug", slug)
                        action = "created"
                        message = f"Term created successfully with ID {woocommerce_term_id}"
                        
                        # Actualizar o crear sync record
                        if existing_sync:
                            repo.update_attribute_value_sync(
                                existing_sync.id,
                                woocommerce_id=woocommerce_term_id,
                                woocommerce_attribute_id=woocommerce_attribute_id,
                                slug=slug,
                                created=True,
                                error=False,
                                message=message
                            )
                        else:
                            repo.create_attribute_value_sync(
                                instance_id=instance_id,
                                odoo_value_id=odoo_value.id,
                                odoo_name=odoo_value.name,
                                woocommerce_id=woocommerce_term_id,
                                woocommerce_attribute_id=woocommerce_attribute_id,
                                slug=slug,
                                created=True,
                                message=message
                            )
                    else:
                        action = "error"
                        message = f"Failed to create term: {create_response}"
                else:
                    action = "skipped"
                    message = "Create disabled, term not created"
            
            results.append(AttributeValueSyncResult(
                odoo_id=odoo_value.id,
                odoo_name=odoo_value.name,
                woocommerce_id=woocommerce_term_id,
                success=(action in ["created", "updated", "skipped"]),
                action=action,
                message=message
            ))
            
        except Exception as e:
            error_msg = f"Error syncing value {odoo_value.id}: {str(e)}"
            _logger.error(error_msg, exc_info=True)
            
            results.append(AttributeValueSyncResult(
                odoo_id=odoo_value.id,
                odoo_name=odoo_value.name,
                woocommerce_id=None,
                success=False,
                action="error",
                message=error_msg,
                error_details=str(e)
            ))
    
    return results


async def get_woocommerce_attributes(
    instance_id: int,
    page: int = 1,
    per_page: int = 100
) -> List[Dict]:
    """
    Obtener todos los atributos de WooCommerce

    Args:
        instance_id: ID de la instancia
        page: Página
        per_page: Items por página

    Returns:
        Lista de atributos desde WooCommerce
    """
    try:
        params = {"page": page, "per_page": per_page}
        response = wc_request("GET", "products/attributes", params=params)

        if isinstance(response, list):
            return response
        return []

    except Exception as e:
        _logger.error(f"Error fetching WooCommerce attributes: {e}")
        return []


async def get_woocommerce_attribute_terms(
    attribute_id: int,
    page: int = 1,
    per_page: int = 100
) -> List[Dict]:
    """
    Obtener terms de un atributo desde WooCommerce

    Args:
        attribute_id: ID del atributo en WooCommerce
        page: Página
        per_page: Items por página

    Returns:
        Lista de terms
    """
    try:
        params = {"page": page, "per_page": per_page}
        response = wc_request(
            "GET", f"products/attributes/{attribute_id}/terms", params=params)

        if isinstance(response, list):
            return response
        return []

    except Exception as e:
        _logger.error(f"Error fetching attribute terms: {e}")
        return []
