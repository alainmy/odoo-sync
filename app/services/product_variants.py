"""
Servicio para sincronización de variantes de productos Odoo ↔ WooCommerce

Integra con la sincronización existente de productos y reutiliza
las funciones de atributos ya implementadas.
"""
import logging
import asyncio
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from app.services.woocommerce import wc_request, wc_request_with_logging
from app.repositories.attribute_repository import AttributeSyncRepository
from app.models.admin import WooCommerceInstance
from app.services.woocommerce.converters import manage_price_list_for_export

_logger = logging.getLogger(__name__)


def has_variants(odoo_product_data: Dict[str, Any]) -> bool:
    """
    Detectar si un product.template de Odoo tiene variantes.

    Args:
        odoo_product_data: Datos del producto desde Odoo

    Returns:
        True si tiene variantes (más de 1 product.product)
    """
    # Verificar si tiene attribute_line_ids (líneas de atributos de variantes)
    attribute_lines = odoo_product_data.get('attribute_line_ids', [])
    _logger.debug(
        f"Attribute lines of product {odoo_product_data.get('name')}: {attribute_lines}")
    # También verificar product_variant_count
    variant_count = odoo_product_data.get('product_variant_count', 1)

    return len(attribute_lines) > 0 and variant_count > 1


def validate_attributes_synced(
    attribute_line_ids: List[int],
    instance_id: int,
    db: Session,
    odoo_client
) -> Dict[str, Any]:
    """
    Validar que todos los atributos y valores estén sincronizados.
    Reutiliza AttributeSyncRepository.

    Returns:
        {"valid": bool, "missing_attributes": [], "missing_values": []}
    """
    repo = AttributeSyncRepository(db)
    missing_attributes = []
    missing_values = []

    # Obtener líneas de atributos completas desde Odoo
    if not attribute_line_ids:
        _logger.info("No attribute lines provided for validation.")
        return {"valid": True, "missing_attributes": [], "missing_values": []}

    try:
        uid = odoo_client.uid
        lines_response = odoo_client.search_read_sync(
            'product.template.attribute.line',
            [['id', 'in', attribute_line_ids]],
            ['attribute_id', 'value_ids']
        )
        _logger.info(f"Validating attribute lines: {lines_response}")
        for line in lines_response:
            # Verificar atributo principal
            attr_id = line.get('attribute_id')
            if isinstance(attr_id, list):
                attr_id = attr_id[0]

            attr_sync = repo.get_by_odoo_id(attr_id, instance_id)

            if not attr_sync or not attr_sync.woocommerce_id:
                missing_attributes.append({
                    'id': attr_id,
                    'name': line.get('attribute_id')[1] if isinstance(line.get('attribute_id'), list) else f"Attribute {attr_id}"
                })
                continue
            _logger.info(
                f"Woo ID: {attr_sync.woocommerce_id}, Odoo ID: {attr_sync.odoo_attribute_id}")
            # Verificar valores del atributo
            value_ids = line.get('value_ids', [])
            _logger.info(
                f"Validating attribute values for attribute {attr_id}: {value_ids}")
            for value_id in value_ids:
                value_sync = repo.get_attribute_value_sync_by_odoo_id(
                    value_id, instance_id)
                _logger.info(
                    f"Woo Value Sync: {value_sync.woocommerce_id}, Odoo Value ID: {value_sync.odoo_value_id}" if value_sync else "No Value Sync Found")
                _logger.info(f"value sync: {value_sync}")
                if not value_sync or not value_sync.woocommerce_id:
                    _logger.info(
                        f"Missing sync for attribute value {value_id} of attribute {attr_id}")
                    missing_values.append({
                        'id': value_id,
                        'attribute_id': attr_id
                    })

        is_valid = len(missing_attributes) == 0 and len(missing_values) == 0

        return {
            "valid": is_valid,
            "missing_attributes": missing_attributes,
            "missing_values": missing_values
        }

    except Exception as e:
        _logger.error(f"Error validating attributes: {e}")
        return {
            "valid": False,
            "error": str(e),
            "missing_attributes": [],
            "missing_values": []
        }


def build_wc_attributes_for_product(
    attribute_line_ids: List[int],
    instance_id: int,
    db: Session,
    odoo_client
) -> List[Dict[str, Any]]:
    """
    Construir array de atributos para WooCommerce variable product.
    Reutiliza AttributeSyncRepository para obtener IDs sincronizados.

    Returns:
        Lista de atributos en formato WC:
        [
            {
                "id": 1,
                "name": "Talla",
                "position": 0,
                "visible": True,
                "variation": True,
                "options": ["S", "M", "L"]
            }
        ]
    """
    repo = AttributeSyncRepository(db)
    wc_attributes = []

    try:
        # Obtener líneas completas desde Odoo
        lines_response = odoo_client.search_read_sync(
            'product.template.attribute.line',
            [['id', 'in', attribute_line_ids]],
            ['attribute_id', 'value_ids', 'sequence']
        )

        for line in lines_response:
            # Obtener atributo sincronizado
            attr_id = line.get('attribute_id')
            if isinstance(attr_id, list):
                attr_id = attr_id[0]
                attr_name = line.get('attribute_id')[1]
            else:
                attr_name = f"Attribute {attr_id}"

            attr_sync = repo.get_by_odoo_id(attr_id, instance_id)
            if not attr_sync or not attr_sync.woocommerce_id:
                _logger.warning(f"Attribute {attr_id} not synced, skipping")
                continue

            # Obtener valores del atributo
            value_ids = line.get('value_ids', [])
            value_names = []

            if value_ids:
                values_response = odoo_client.search_read_sync(
                    'product.attribute.value',
                    [['id', 'in', value_ids]],
                    ['name']
                )
                value_names = [v.get('name', '') for v in values_response]

            wc_attributes.append({
                "id": attr_sync.woocommerce_id,
                "name": attr_name,
                "position": line.get('sequence', 0),
                "visible": True,
                "variation": True,  # Usado para variaciones
                "options": value_names
            })

        return wc_attributes

    except Exception as e:
        _logger.error(f"Error building WC attributes: {e}")
        return []


def build_variation_attributes(
    variant_attribute_values: List[int],
    instance_id: int,
    db: Session,
    odoo_client
) -> List[Dict[str, Any]]:
    """
    Construir atributos específicos de una variación.

    Args:
        variant_attribute_values: IDs de product.template.attribute.value

    Returns:
        [{"id": 1, "option": "s"}, {"id": 2, "option": "rojo"}]
    """
    repo = AttributeSyncRepository(db)
    wc_variation_attrs = []

    try:
        if not variant_attribute_values:
            return []

        # Obtener valores completos desde Odoo
        values_response = odoo_client.search_read_sync(
            'product.template.attribute.value',
            [['id', 'in', variant_attribute_values]],
            ['attribute_id', 'product_attribute_value_id', 'name']
        )

        for ptav in values_response:
            # Obtener atributo
            attr_id = ptav.get('attribute_id')
            if isinstance(attr_id, list):
                attr_id = attr_id[0]

            attr_sync = repo.get_by_odoo_id(attr_id, instance_id)
            if not attr_sync:
                continue

            # Nombre del valor (en minúsculas para WC)
            value_name = ptav.get('name', '').lower()

            wc_variation_attrs.append({
                "id": attr_sync.woocommerce_id,
                "option": value_name
            })

        return wc_variation_attrs

    except Exception as e:
        _logger.error(f"Error building variation attributes: {e}")
        return []


async def sync_product_variations(
    odoo_template_id: int,
    wc_parent_id: int,
    instance_id: int,
    db: Session,
    odoo_client,
    wcapi=None
) -> Dict[str, Any]:
    """
    Sincronizar todas las variaciones de un product.template.

    Args:
        odoo_template_id: ID del product.template en Odoo
        wc_parent_id: ID del variable product en WooCommerce
        instance_id: ID de la instancia
        db: Sesión de base de datos
        odoo_client: Cliente de Odoo
        wcapi: API de WooCommerce

    Returns:
        {"success": bool, "synced": int, "errors": int, "results": []}
    """
    results = []
    synced_count = 0
    updated_count = 0
    error_count = 0

    try:
        # Obtener todas las variantes activas del template
        variants_response = odoo_client.search_read_sync(
            'product.product',
            [
                ['product_tmpl_id', '=', odoo_template_id],
                ['active', '=', True]
            ],
            [
                'id', 'default_code', 'lst_price', 'qty_available',
                'product_tmpl_id',
                'product_template_variant_value_ids', 'image_1920',
                'display_name'
            ]
        )

        _logger.info(
            f"Found {len(variants_response)} variants for template {odoo_template_id}")

        for variant in variants_response:
            try:
                variant_id = variant.get('id')
                product_tmpl_id = variant.get('product_tmpl_id', '')[0] if isinstance(
                    variant.get('product_tmpl_id'), list) else None
                # sku = variant.get('default_code', '')
                sku = variant.get('product_tmpl_id', '')[1] if isinstance(
                    variant.get('product_tmpl_id'), list) else None
                sku = f"{sku.replace(' ', '-').upper()}-{variant_id}" if sku else f"variant-{variant_id}"

                # manage price
                price = variant.get('lst_price', 0)
                instance = db.query(WooCommerceInstance).filter(
                    WooCommerceInstance.id == instance_id).first()
                if instance.price_list:
                    price = manage_price_list_for_export(
                        db=db,
                        odoo_client=odoo_client,
                        product_id=variant_id,
                        product_tmpl_id=product_tmpl_id,
                        instance_id=instance_id
                    )
                    price = str(price) if price else None
                stock = variant.get('qty_available', 0)
                variant_value_ids = variant.get(
                    'product_template_variant_value_ids', [])
                _logger.info(
                    f"Syncing variant {variant_id} (SKU: {sku}) with name {variant.get('display_name')}")
                # Construir atributos de la variación
                variation_attrs = build_variation_attributes(
                    variant_value_ids,
                    instance_id,
                    db,
                    odoo_client
                )
                _logger.info(
                    f"Built variation attributes for variant {variant_id}: {variation_attrs}")

                # Preparar datos para WooCommerce
                wc_variation_data = {
                    "sku": str(sku or ""),  # ✅ Asegurar que siempre sea string
                    "regular_price": str(price or "0"),
                    "stock_quantity": int(stock or 0),
                    "manage_stock": True,
                    "attributes": variation_attrs
                }
                _logger.info(
                    f"Built variation data for variant {variant_id}: {wc_variation_data}")
                # Buscar si exite la cariante
                variant_exist = None
                params_search = {"per_page": 1}
                _logger.info(
                    f"Searching for existing variants of product with sku: {sku} in WooCommerce.")
                if sku:
                    _logger.info(
                        f"Searching for existing variant with SKU {sku} in WooCommerce.")
                    params_search["sku"] = sku
                    variant_matches = wc_request_with_logging(
                        "GET",
                        f"products/{wc_parent_id}/variations",
                        params={"sku": sku},
                        wcapi=wcapi
                    )
                    if variant_matches:
                        _logger.info(
                            f"Variant with SKU {sku} exists in WooCommerce.")
                        for matches in variant_matches:
                            if matches.get("sku") == sku:
                                variant_exist = matches
                                break
                        _logger.info(
                            f"Updating existing variant {variant_exist.get('id')} for SKU {sku}.")
                        response = wc_request_with_logging(
                            "PUT",
                            f"products/{wc_parent_id}/variations/{variant_exist.get('id')}",
                            params=wc_variation_data,
                            wcapi=wcapi
                        )
                        updated_count = updated_count + 1
                        _logger.info(f"Variant update response: {response}")
                _logger.info(f"Variant exist: {variant_exist}")
                # Crear variación en WooCommerce
                if not variant_exist:
                    _logger.info(
                        f"Creating new variant for SKU {sku} in WooCommerce.")
                    _logger.info(
                        f"Variation data to create: {wc_variation_data}")
                    response = wc_request_with_logging(
                        "POST",
                        f"products/{wc_parent_id}/variations",
                        params=wc_variation_data,
                        wcapi=wcapi
                    )
                    _logger.info(f"Variant creation response: {response}")
                    if response and isinstance(response, dict) and "id" in response:
                        synced_count += 1
                        results.append({
                            "odoo_id": variant_id,
                            "wc_id": response["id"],
                            "sku": sku,
                            "success": True,
                            "message": f"Variation created with ID {response['id']}"
                        })
                        _logger.info(
                            f"Variation {sku} created: WC ID {response['id']}")
                    else:
                        _logger.error(
                            f"Failed to create variation {sku}: {response}")
                        error_count += 1
                        results.append({
                            "odoo_id": variant_id,
                            "sku": sku,
                            "success": False,
                            "message": f"Failed to create variation: {response}"
                        })

            except Exception as e:
                error_count += 1
                _logger.error(
                    f"Error syncing variant {variant.get('id')}: {e}")
                results.append({
                    "odoo_id": variant.get('id'),
                    "success": False,
                    "message": str(e)
                })

        return {
            "success": error_count == 0,
            "synced": synced_count,
            "updated": updated_count,
            "errors": error_count,
            "results": results
        }

    except Exception as e:
        _logger.error(f"Error syncing variations: {e}")
        return {
            "success": False,
            "synced": 0,
            "errors": 1,
            "message": str(e),
            "results": []
        }


def sync_product_variations_sync(
    odoo_client: Any,
    template_id: int,
    wc_parent_id: int,
    db: Session,
    wcapi,
    instance_id: int
) -> Dict[str, Any]:
    """
    Synchronous wrapper for sync_product_variations.
    For use in Celery tasks that run in synchronous context.

    Args:
        odoo_client: Authenticated Odoo client
        template_id: Odoo product.template ID
        wc_parent_id: WooCommerce parent product ID
        db: Database session
        wcapi: WooCommerce API client
        instance_id: Instance ID for attribute validation

    Returns:
        Dict with sync results including success status, counts, and errors
    """
    # Run the async function in a new event loop
    return asyncio.run(
        sync_product_variations(
            odoo_client=odoo_client,
            odoo_template_id=template_id,
            wc_parent_id=wc_parent_id,
            db=db,
            wcapi=wcapi,
            instance_id=instance_id
        )
    )
