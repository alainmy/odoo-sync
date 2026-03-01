"""
Order sync repository.

Handles all order synchronization database operations.
"""
import logging
from typing import Optional, List, Dict
from datetime import datetime
from app.repositories.base_sync_repository import BaseSyncRepository
from app.models.order_model import OrderSync

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class OrderSyncRepository(BaseSyncRepository[OrderSync]):
    """Repository for order sync operations."""

    model_class = OrderSync

    def get_order_sync_by_woo_id(
        self,
        woo_id: int,
        instance_id: int
    ) -> Optional[OrderSync]:
        """
        Get order sync record by WooCommerce ID.

        Args:
            woo_id: WooCommerce order ID
            instance_id: WooCommerce instance ID

        Returns:
            OrderSync record or None
        """
        return self.db.query(OrderSync).filter(
            OrderSync.woo_id == woo_id,
            OrderSync.instance_id == instance_id
        ).first()

    def get_order_sync_statistics(
        self,
        instance_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, int]:
        """
        Get order sync statistics.

        Args:
            instance_id: WooCommerce instance ID
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary with sync statistics
        """
        query = self.db.query(OrderSync).filter(
            OrderSync.instance_id == instance_id
        )

        total = query.count()
        created = query.filter(OrderSync.created is True).count()
        updated = query.filter(OrderSync.updated is True).count()
        skipped = query.filter(OrderSync.skipped is True).count()
        errors = query.filter(OrderSync.error is True).count()

        return {
            "total": total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }

    def add_order_sync(
        self,
        woo_id: int,
        instance_id: int,
        **kwargs
    ) -> OrderSync:
        """Agrega un nuevo registro de sincronización de orden."""
        order = OrderSync(woo_id=woo_id, instance_id=instance_id, **kwargs)
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def update_order_sync(
        self,
        order_id: int,
        instance_id: int,
        **kwargs
    ) -> Optional[OrderSync]:
        """Actualiza un registro de sincronización existente."""
        order = self.db.query(OrderSync).filter(
            OrderSync.id == order_id,
            OrderSync.instance_id == instance_id
        ).first()
        if not order:
            return None
        for key, value in kwargs.items():
            setattr(order, key, value)
        self.db.commit()
        self.db.refresh(order)
        return order

    def delete_order_sync(
        self,
        order_id: int,
        instance_id: int
    ) -> bool:
        """Elimina un registro de sincronización de orden."""
        order = self.db.query(OrderSync).filter(
            OrderSync.id == order_id,
            OrderSync.instance_id == instance_id
        ).first()
        if not order:
            return False
        self.db.delete(order)
        self.db.commit()
        return True

    def list_order_syncs(
        self,
        instance_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[OrderSync]:
        """Lista registros de sincronización de órdenes para una instancia."""
        return self.db.query(OrderSync).filter(
            OrderSync.instance_id == instance_id
        ).offset(offset).limit(limit).all()

