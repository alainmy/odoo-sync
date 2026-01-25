"""
Servicio para obtener atributos desde Odoo vía XML-RPC

Conecta con Odoo para obtener:
- product.attribute (atributos como Color, Talla, etc.)
- product.attribute.value (valores como Rojo, S, M, etc.)
"""
import logging
from typing import List, Optional, Dict
from app.crud.odoo import OdooClient
from app.schemas.attributes import OdooAttribute, OdooAttributeValue

_logger = logging.getLogger(__name__)


async def get_odoo_attributes(
    odoo_client: OdooClient,
    limit: int = 100,
    offset: int = 0,
    name_filter: Optional[str] = None
) -> List[OdooAttribute]:
    """
    Obtener atributos desde Odoo (product.attribute)
    
    Args:
        odoo_client: Cliente autenticado de Odoo
        limit: Límite de resultados
        offset: Offset para paginación
        name_filter: Filtro por nombre (opcional)
        
    Returns:
        Lista de atributos con sus valores
    """
    try:
        # Autenticar
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            _logger.error("Failed to authenticate with Odoo")
            return []
        
        # Construir dominio de búsqueda
        domain = []
        if name_filter:
            domain.append(["name", "ilike", name_filter])
        
        # Campos a obtener de product.attribute
        attribute_fields = [
            "id",
            "name",
            "display_type",
            "create_variant",
            "value_ids"  # IDs de los valores relacionados
        ]
        
        # Obtener atributos
        _logger.info(f"Fetching attributes from Odoo (limit={limit}, offset={offset})")
        attributes_response = await odoo_client.search_read(
            uid=uid,
            model="product.attribute",
            domain=domain,
            limit=limit,
            offset=offset,
            fields=attribute_fields
        )
        
        if attributes_response.get("error"):
            error_msg = attributes_response["error"].get("message", "Unknown error")
            _logger.error(f"Error fetching attributes from Odoo: {error_msg}")
            return []
        
        attributes_data = attributes_response.get("result", [])
        _logger.info(f"Found {len(attributes_data)} attributes in Odoo")
        
        # Procesar cada atributo y obtener sus valores
        odoo_attributes = []
        for attr_data in attributes_data:
            attribute_id = attr_data.get("id")
            value_ids = attr_data.get("value_ids", [])
            
            # Obtener valores del atributo
            attribute_values = []
            if value_ids:
                values_data = await get_odoo_attribute_values(
                    odoo_client=odoo_client,
                    uid=uid,
                    value_ids=value_ids
                )
                attribute_values = values_data
            
            # Crear schema OdooAttribute
            odoo_attribute = OdooAttribute(
                id=attribute_id,
                name=attr_data.get("name", ""),
                display_type=attr_data.get("display_type", "radio"),
                create_variant=attr_data.get("create_variant", "always"),
                values=attribute_values
            )
            
            odoo_attributes.append(odoo_attribute)
            _logger.debug(
                f"Attribute '{odoo_attribute.name}' (ID: {attribute_id}) "
                f"has {len(attribute_values)} values"
            )
        
        return odoo_attributes
        
    except Exception as e:
        _logger.error(f"Exception fetching attributes from Odoo: {str(e)}")
        return []


async def get_odoo_attribute_values(
    odoo_client: OdooClient,
    uid: int,
    value_ids: List[int]
) -> List[OdooAttributeValue]:
    """
    Obtener valores de atributos desde Odoo (product.attribute.value)
    
    Args:
        odoo_client: Cliente de Odoo
        uid: User ID autenticado
        value_ids: Lista de IDs de valores a obtener
        
    Returns:
        Lista de valores del atributo
    """
    try:
        if not value_ids:
            return []
        
        # Campos a obtener de product.attribute.value
        value_fields = [
            "id",
            "name",
            "html_color",
            "display_type"
        ]
        
        # Buscar valores por IDs
        values_response = await odoo_client.search_read(
            uid=uid,
            model="product.attribute.value",
            domain=[["id", "in", value_ids]],
            limit=len(value_ids),
            offset=0,
            fields=value_fields
        )
        
        if values_response.get("error"):
            error_msg = values_response["error"].get("message", "Unknown error")
            _logger.error(f"Error fetching attribute values from Odoo: {error_msg}")
            return []
        
        values_data = values_response.get("result", [])
        
        # Convertir a OdooAttributeValue
        attribute_values = [
            OdooAttributeValue(
                id=value.get("id"),
                name=value.get("name", ""),
                html_color=value.get("html_color"),
                display_type=value.get("display_type", "radio")
            )
            for value in values_data
        ]
        
        return attribute_values
        
    except Exception as e:
        _logger.error(f"Exception fetching attribute values: {str(e)}")
        return []


async def get_odoo_attribute_by_id(
    odoo_client: OdooClient,
    attribute_id: int
) -> Optional[OdooAttribute]:
    """
    Obtener un atributo específico desde Odoo por ID
    
    Args:
        odoo_client: Cliente de Odoo
        attribute_id: ID del atributo en Odoo
        
    Returns:
        Atributo con sus valores o None si no se encuentra
    """
    try:
        uid = await odoo_client.odoo_authenticate()
        if not uid:
            return None
        
        # Obtener atributo
        attribute_response = await odoo_client.search_read(
            uid=uid,
            model="product.attribute",
            domain=[["id", "=", attribute_id]],
            limit=1,
            offset=0,
            fields=["id", "name", "display_type", "create_variant", "value_ids"]
        )
        
        if attribute_response.get("error"):
            return None
        
        attributes = attribute_response.get("result", [])
        if not attributes:
            _logger.warning(f"Attribute ID {attribute_id} not found in Odoo")
            return None
        
        attr_data = attributes[0]
        value_ids = attr_data.get("value_ids", [])
        
        # Obtener valores
        attribute_values = []
        if value_ids:
            attribute_values = await get_odoo_attribute_values(
                odoo_client=odoo_client,
                uid=uid,
                value_ids=value_ids
            )
        
        return OdooAttribute(
            id=attr_data.get("id"),
            name=attr_data.get("name", ""),
            display_type=attr_data.get("display_type", "radio"),
            create_variant=attr_data.get("create_variant", "always"),
            values=attribute_values
        )
        
    except Exception as e:
        _logger.error(f"Exception fetching attribute {attribute_id}: {str(e)}")
        return None


async def search_odoo_attributes_by_name(
    odoo_client: OdooClient,
    name: str,
    limit: int = 10
) -> List[OdooAttribute]:
    """
    Buscar atributos en Odoo por nombre
    
    Args:
        odoo_client: Cliente de Odoo
        name: Nombre o parte del nombre a buscar
        limit: Límite de resultados
        
    Returns:
        Lista de atributos que coinciden
    """
    return await get_odoo_attributes(
        odoo_client=odoo_client,
        limit=limit,
        offset=0,
        name_filter=name
    )
