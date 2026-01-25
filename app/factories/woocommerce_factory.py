"""Factory for creating WooCommerce API clients."""

from typing import Dict
from woocommerce import API

from app.core.config import settings
from app.models.admin import WooCommerceInstance


class WooCommerceClientFactory:
    """Factory class for creating WooCommerce API clients."""
    
    @staticmethod
    def from_instance(instance: WooCommerceInstance) -> API:
        """
        Create a WooCommerce API client from a WooCommerceInstance model.
        
        Args:
            instance: WooCommerceInstance database model
            
        Returns:
            API: Configured WooCommerce API client
        """
        return API(
            url=instance.woocommerce_url,
            consumer_key=instance.woocommerce_consumer_key,
            consumer_secret=instance.woocommerce_consumer_secret,
            wp_api=True,
            version=settings.wc_api_version,
            timeout=settings.wc_request_timeout,
            verify_ssl=settings.wc_verify_ssl
        )
    
    @staticmethod
    def from_config(config: Dict[str, str]) -> API:
        """
        Create a WooCommerce API client from a configuration dictionary.
        
        Args:
            config: Dictionary with keys 'url', 'consumer_key', 'consumer_secret'
            
        Returns:
            API: Configured WooCommerce API client
        """
        return API(
            url=config["url"],
            consumer_key=config["consumer_key"],
            consumer_secret=config["consumer_secret"],
            wp_api=True,
            version=settings.wc_api_version,
            timeout=settings.wc_request_timeout,
            verify_ssl=settings.wc_verify_ssl
        )
    
    @staticmethod
    def from_credentials(
        url: str,
        consumer_key: str,
        consumer_secret: str
    ) -> API:
        """
        Create a WooCommerce API client from individual credentials.
        
        Args:
            url: WooCommerce store URL
            consumer_key: WooCommerce consumer key
            consumer_secret: WooCommerce consumer secret
            
        Returns:
            API: Configured WooCommerce API client
        """
        return API(
            url=url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            wp_api=True,
            version=settings.wc_api_version,
            timeout=settings.wc_request_timeout,
            verify_ssl=settings.wc_verify_ssl
        )
