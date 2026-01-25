"""
WooCommerce instance repository.

Handles WooCommerce instance configuration database operations.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.admin import WooCommerceInstance


class InstanceRepository:
    """Repository for WooCommerce instance operations."""
    
    def __init__(self, db: Session):
        """
        Initialize repository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def create_instance(
        self,
        name: str,
        url: str,
        consumer_key: str,
        consumer_secret: str,
        webhook_secret: str,
        **kwargs
    ) -> WooCommerceInstance:
        """
        Create a WooCommerce instance configuration.
        
        Args:
            name: Instance name
            url: WooCommerce store URL
            consumer_key: WooCommerce API consumer key
            consumer_secret: WooCommerce API consumer secret
            webhook_secret: Webhook verification secret
            **kwargs: Additional instance fields
            
        Returns:
            Created WooCommerceInstance record
        """
        instance = WooCommerceInstance(
            name=name,
            url=url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            webhook_secret=webhook_secret,
            **kwargs
        )
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance
    
    def get_instance(self, instance_id: int) -> Optional[WooCommerceInstance]:
        """
        Get WooCommerce instance by ID.
        
        Args:
            instance_id: Instance ID
            
        Returns:
            WooCommerceInstance record or None
        """
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.id == instance_id
        ).first()
    
    def get_instance_by_name(self, name: str) -> Optional[WooCommerceInstance]:
        """
        Get WooCommerce instance by name.
        
        Args:
            name: Instance name
            
        Returns:
            WooCommerceInstance record or None
        """
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.name == name
        ).first()
    
    def get_active_instances(self) -> List[WooCommerceInstance]:
        """
        Get all active WooCommerce instances.
        
        Returns:
            List of active WooCommerceInstance records
        """
        return self.db.query(WooCommerceInstance).filter(
            WooCommerceInstance.is_active == True
        ).all()
    
    def get_all_instances(self) -> List[WooCommerceInstance]:
        """
        Get all WooCommerce instances.
        
        Returns:
            List of all WooCommerceInstance records
        """
        return self.db.query(WooCommerceInstance).all()
