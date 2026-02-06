"""WooCommerce API client utilities."""

import logging
import requests
from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from woocommerce import API

from app.core.config import settings
from app.crud import crud_instance
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.db.session import get_db
from app.factories.woocommerce_factory import WooCommerceClientFactory

__logger__ = logging.getLogger(__name__)


def get_wc_api_from_instance_config(wc_config: Dict[str, str]) -> API:
    """
    Crea un cliente de WooCommerce API con las configuraciones de la instancia.
    
    Args:
        wc_config: Dict con keys: url, consumer_key, consumer_secret
        
    Returns:
        API client configurado
    """
    return WooCommerceClientFactory.from_config(wc_config)


def get_wc_api_from_active_instance(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
) -> API:
    """
    Dependency injection que retorna un cliente de WooCommerce configurado
    con las credenciales de la instancia activa del usuario actual.
    
    Raises:
        HTTPException 404: Si el usuario no tiene una instancia activa
        HTTPException 500: Si hay error al crear el cliente
    """
    instance = crud_instance.get_active_instance(db, user_id=current_user.id)
    if not instance:
        raise HTTPException(status_code=404, detail="No active instance found")
    
    try:
        return WooCommerceClientFactory.from_instance(instance)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create WooCommerce API client: {str(e)}"
        )


def wc_get(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """Execute GET request to WooCommerce API."""
    # CRITICAL FIX: Pass params to wcapi.get() for filtering (SKU, slug, etc.)
    r = wcapi.get(path, params=params) if params else wcapi.get(path)
    if not r.ok:
        # Log the error and raise a regular exception for Celery retry
        __logger__.error(f"WooCommerce GET error on {path}: {r.status_code} - {r.text}")
        raise Exception(
            f"WooCommerce API error ({r.status_code}): {r.text}"
        )
    return r.json()


def wc_post(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """Execute POST request to WooCommerce API."""
    r = wcapi.post(path, params)
    if not r.ok:
        # Log the error and raise a regular exception for Celery retry
        __logger__.error(f"WooCommerce POST error on {path}: {r.status_code} - {r.text}")
        raise Exception(f"WooCommerce POST error on {path}: {r.status_code} - {r.text}")
    return r.json()


def wc_put(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """Execute PUT request to WooCommerce API."""
    # params is the request body for PUT
    r = wcapi.put(path, params) if params else wcapi.put(path, {})
    if not r.ok:
        # Log the error and raise a regular exception for Celery retry
        __logger__.error(f"WooCommerce PUT error on {path}: {r.status_code} - {r.text}")
        raise Exception(
            f"WooCommerce API error ({r.status_code}): {r.text}"
        )
    return r.json()


def wc_delete(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """Execute DELETE request to WooCommerce API."""
    # params can be used for query parameters like force=true
    r = wcapi.delete(path, params=params) if params else wcapi.delete(path)
    if not r.ok:
        # Log the error and raise a regular exception for Celery retry
        __logger__.error(f"WooCommerce DELETE error on {path}: {r.status_code} - {r.text}")
        raise Exception(
            f"WooCommerce API error ({r.status_code}): {r.text}"
        )
    return r.json()


def wc_request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """
    Generic WooCommerce API request handler.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API endpoint path
        params: Request parameters/data
        wcapi: WooCommerce API client (creates default if None)
        
    Returns:
        JSON response from WooCommerce
    """
    # Fallback a settings si no se proporciona wcapi
    if wcapi is None:
        wcapi = WooCommerceClientFactory.from_credentials(
            url=settings.wc_base_url,
            consumer_key=settings.wc_consumer_key,
            consumer_secret=settings.wc_consumer_secret
        )
    
    response_json = None
    if method == "GET":
        response_json = wc_get(method, path, params, wcapi)
    elif method == "POST":
        response_json = wc_post(method, path, params, wcapi)
    elif method == "PUT":
        response_json = wc_put(method, path, params, wcapi)
    elif method == "DELETE":
        response_json = wc_delete(method, path, params, wcapi)
    
    return response_json


def wc_request_post(
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """
    Legacy POST request handler using requests library directly.
    Consider migrating to wc_request() for consistency.
    
    Args:
        method: HTTP method
        path: API endpoint path
        data: Request body data
        wcapi: WooCommerce API client
        
    Returns:
        JSON response
    """
    # Fallback a settings si no se proporciona wcapi
    if wcapi is None:
        wcapi = WooCommerceClientFactory.from_credentials(
            url=settings.wc_base_url,
            consumer_key=settings.wc_consumer_key,
            consumer_secret=settings.wc_consumer_secret
        )
    
    url = f"{wcapi.url}{path}"
    auth = (wcapi.consumer_key, wcapi.consumer_secret)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Host": "woocommerce.localhost"
    }
    
    r = requests.request(
        method, url,
        headers=headers,
        json=data,
        auth=auth,
        timeout=settings.wc_request_timeout,
        verify=settings.wc_verify_ssl
    )
    
    if not r.ok:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"WooCommerce error: {r.text}"
        )
    
    return r.json()

def wc_request_with_logging(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    wcapi: API = None
) -> Any:
    """
    WooCommerce request with detailed logging.
    Wrapper around wc_request with enhanced logging for debugging.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API endpoint path
        params: Request parameters or body data
        wcapi: WooCommerce API client
        
    Returns:
        JSON response
    """
    __logger__.debug(f"WC Request: {method} {path} with params: {params}")
    
    try:
        result = wc_request(method, path, params, wcapi)
        __logger__.debug(f"WC Response: {result}")
        return result
    except Exception as e:
        __logger__.error(f"WC Request failed: {method} {path} - Error: {e}")
        raise