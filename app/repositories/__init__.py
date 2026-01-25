"""
Repository layer for database operations.

This package provides specialized repositories for different domains:
- ProductSyncRepository: Product synchronization operations
- CategorySyncRepository: Category synchronization operations  
- TagSyncRepository: Tag synchronization operations
- WebhookRepository: Webhook log operations
- TaskLogRepository: Celery task log operations
- InstanceRepository: WooCommerce instance configuration operations

All sync repositories inherit from BaseSyncRepository for common CRUD operations.
"""
from app.repositories.base_sync_repository import BaseSyncRepository
from app.repositories.product_sync_repository import ProductSyncRepository
from app.repositories.category_sync_repository import CategorySyncRepository
from app.repositories.tag_sync_repository import TagSyncRepository
from app.repositories.webhook_repository import WebhookRepository
from app.repositories.task_log_repository import TaskLogRepository
from app.repositories.instance_repository import InstanceRepository

# For backward compatibility - maintain SyncRepository facade
from sqlalchemy.orm import Session


class SyncRepository:
    """
    Legacy SyncRepository facade for backward compatibility.
    
    DEPRECATED: Use specialized repositories instead:
    - ProductSyncRepository for product operations
    - CategorySyncRepository for category operations
    - TagSyncRepository for tag operations
    - WebhookRepository for webhook logs
    - TaskLogRepository for task logs
    - InstanceRepository for instance configuration
    
    This facade delegates to the specialized repositories.
    Will be removed in version 2.0.
    """
    
    def __init__(self, db: Session):
        """Initialize all specialized repositories."""
        self.db = db
        self._product_repo = ProductSyncRepository(db)
        self._category_repo = CategorySyncRepository(db)
        self._tag_repo = TagSyncRepository(db)
        self._webhook_repo = WebhookRepository(db)
        self._task_log_repo = TaskLogRepository(db)
        self._instance_repo = InstanceRepository(db)
    
    # Product sync methods - delegate to ProductSyncRepository
    def create_product_sync(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.create_sync()"""
        return self._product_repo.create_sync(*args, **kwargs)
    
    def get_product_sync_by_odoo_id(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_sync_by_odoo_id()"""
        return self._product_repo.get_sync_by_odoo_id(*args, **kwargs)
    
    def get_product_sync_by_wc_id(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_product_sync_by_wc_id()"""
        return self._product_repo.get_product_sync_by_wc_id(*args, **kwargs)
    
    def update_product_sync(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.update_sync()"""
        return self._product_repo.update_sync(*args, **kwargs)
    
    def get_product_sync_statistics(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_product_sync_statistics()"""
        return self._product_repo.get_product_sync_statistics(*args, **kwargs)
    
    def get_product_syncs(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_syncs()"""
        return self._product_repo.get_syncs(*args, **kwargs)
    
    def get_products_with_sync_status(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_products_with_sync_status()"""
        return self._product_repo.get_products_with_sync_status(*args, **kwargs)
    
    def mark_products_for_sync(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.mark_products_for_sync()"""
        return self._product_repo.mark_products_for_sync(*args, **kwargs)
    
    def get_products_needing_sync(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.get_products_needing_sync()"""
        return self._product_repo.get_products_needing_sync(*args, **kwargs)
    
    def update_product_sync_timestamps(self, *args, **kwargs):
        """DEPRECATED: Use ProductSyncRepository.update_product_sync_timestamps()"""
        return self._product_repo.update_product_sync_timestamps(*args, **kwargs)
    
    # Category sync methods - delegate to CategorySyncRepository
    def create_category_sync(self, *args, **kwargs):
        """DEPRECATED: Use CategorySyncRepository.create_sync()"""
        return self._category_repo.create_sync(*args, **kwargs)
    
    def get_category_sync_by_odoo_id(self, *args, **kwargs):
        """DEPRECATED: Use CategorySyncRepository.get_sync_by_odoo_id()"""
        return self._category_repo.get_sync_by_odoo_id(*args, **kwargs)
    
    def get_category_syncs(self, *args, **kwargs):
        """DEPRECATED: Use CategorySyncRepository.get_syncs()"""
        return self._category_repo.get_syncs(*args, **kwargs)
    
    def get_category_sync_stats(self, *args, **kwargs):
        """DEPRECATED: Use CategorySyncRepository.get_sync_stats()"""
        return self._category_repo.get_sync_stats(*args, **kwargs)
    
    # Tag sync methods - delegate to TagSyncRepository
    def create_tag_sync(self, *args, **kwargs):
        """DEPRECATED: Use TagSyncRepository.create_sync()"""
        return self._tag_repo.create_sync(*args, **kwargs)
    
    def get_tag_sync_by_odoo_id(self, *args, **kwargs):
        """DEPRECATED: Use TagSyncRepository.get_sync_by_odoo_id()"""
        return self._tag_repo.get_sync_by_odoo_id(*args, **kwargs)
    
    def get_tag_syncs(self, *args, **kwargs):
        """DEPRECATED: Use TagSyncRepository.get_syncs()"""
        return self._tag_repo.get_syncs(*args, **kwargs)
    
    def get_tag_sync_stats(self, *args, **kwargs):
        """DEPRECATED: Use TagSyncRepository.get_sync_stats()"""
        return self._tag_repo.get_sync_stats(*args, **kwargs)
    
    # Webhook methods - delegate to WebhookRepository
    def create_webhook_log(self, *args, **kwargs):
        """DEPRECATED: Use WebhookRepository.create_webhook_log()"""
        return self._webhook_repo.create_webhook_log(*args, **kwargs)
    
    def get_webhook_log_by_event_id(self, *args, **kwargs):
        """DEPRECATED: Use WebhookRepository.get_webhook_log_by_event_id()"""
        return self._webhook_repo.get_webhook_log_by_event_id(*args, **kwargs)
    
    def get_webhook_logs(self, *args, **kwargs):
        """DEPRECATED: Use WebhookRepository.get_webhook_logs()"""
        return self._webhook_repo.get_webhook_logs(*args, **kwargs)
    
    def update_webhook_log(self, *args, **kwargs):
        """DEPRECATED: Use WebhookRepository.update_webhook_log()"""
        return self._webhook_repo.update_webhook_log(*args, **kwargs)
    
    def get_webhook_statistics(self, *args, **kwargs):
        """DEPRECATED: Use WebhookRepository.get_webhook_statistics()"""
        return self._webhook_repo.get_webhook_statistics(*args, **kwargs)
    
    # Task log methods - delegate to TaskLogRepository
    def create_task_log(self, *args, **kwargs):
        """DEPRECATED: Use TaskLogRepository.create_task_log()"""
        return self._task_log_repo.create_task_log(*args, **kwargs)
    
    def get_task_log(self, *args, **kwargs):
        """DEPRECATED: Use TaskLogRepository.get_task_log()"""
        return self._task_log_repo.get_task_log(*args, **kwargs)
    
    def update_task_log(self, *args, **kwargs):
        """DEPRECATED: Use TaskLogRepository.update_task_log()"""
        return self._task_log_repo.update_task_log(*args, **kwargs)
    
    def get_task_logs(self, *args, **kwargs):
        """DEPRECATED: Use TaskLogRepository.get_task_logs()"""
        return self._task_log_repo.get_task_logs(*args, **kwargs)
    
    # Instance methods - delegate to InstanceRepository
    def create_instance(self, *args, **kwargs):
        """DEPRECATED: Use InstanceRepository.create_instance()"""
        return self._instance_repo.create_instance(*args, **kwargs)
    
    def get_instance(self, *args, **kwargs):
        """DEPRECATED: Use InstanceRepository.get_instance()"""
        return self._instance_repo.get_instance(*args, **kwargs)
    
    def get_instance_by_name(self, *args, **kwargs):
        """DEPRECATED: Use InstanceRepository.get_instance_by_name()"""
        return self._instance_repo.get_instance_by_name(*args, **kwargs)
    
    def get_active_instances(self, *args, **kwargs):
        """DEPRECATED: Use InstanceRepository.get_active_instances()"""
        return self._instance_repo.get_active_instances(*args, **kwargs)
    
    def get_all_instances(self, *args, **kwargs):
        """DEPRECATED: Use InstanceRepository.get_all_instances()"""
        return self._instance_repo.get_all_instances(*args, **kwargs)


def get_sync_repository(db: Session) -> SyncRepository:
    """
    Dependency injection for SyncRepository.
    
    DEPRECATED: Use specialized repository classes directly.
    """
    return SyncRepository(db)


__all__ = [
    'BaseSyncRepository',
    'ProductSyncRepository',
    'CategorySyncRepository',
    'TagSyncRepository',
    'WebhookRepository',
    'TaskLogRepository',
    'InstanceRepository',
    'SyncRepository',  # Legacy facade
    'get_sync_repository',  # Legacy DI function
]
