"""
Celery application configuration for WooCommerce-Odoo sync microservice.
"""
from celery import Celery
from app.core.config import settings

# Create Celery instance
celery_app = Celery(
    "woocommerce_odoo_sync",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.sync_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.scheduled_tasks",
        "app.tasks.attribute_tasks",
        "app.tasks.pricelist_tasks",
    ]
)

# Configure Celery for optimal performance
celery_app.conf.update(
    # Serialization
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content,
    
    # Timezone
    timezone=settings.celery_timezone,
    enable_utc=settings.celery_enable_utc,
    
    # Task execution
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    
    # Worker optimization for I/O-bound tasks (API calls)
    worker_prefetch_multiplier=4,  # Prefetch 4 tasks per worker
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    worker_concurrency=4,  # 4 concurrent workers (adjust based on CPU)
    
    # Task acknowledgment - important for reliability
    task_acks_late=True,  # Acknowledge after task completion
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    
    # Result backend optimization
    result_expires=7200,  # Keep results for 2 hours
    result_backend_transport_options={
        'master_name': 'mymaster',
        'visibility_timeout': 3600,  # 1 hour visibility
    },
    
    # Task routes for prioritization
    task_routes={
        'app.tasks.sync_tasks.sync_product_to_woocommerce': {
            'queue': 'sync_queue',
            'priority': 5
        },
        'app.tasks.sync_tasks.full_product_sync_wc_to_odoo': {
            'queue': 'sync_queue',
            'priority': 3
        },
        'app.tasks.pricelist_tasks.sync_product_prices': {
            'queue': 'sync_queue',
            'priority': 6
        },
        'app.tasks.pricelist_tasks.sync_all_product_prices': {
            'queue': 'sync_queue',
            'priority': 4
        },
        'app.tasks.pricelist_tasks.scheduled_price_sync': {
            'queue': 'scheduler_queue',
            'priority': 6
        },
        'app.tasks.pricelist_tasks.fetch_odoo_pricelists': {
            'queue': 'sync_queue',
            'priority': 9
        },
        'app.tasks.scheduled_tasks.*': {
            'queue': 'scheduler_queue',
            'priority': 7
        },
        'app.tasks.webhook_tasks.*': {
            'queue': 'webhook_queue',
            'priority': 8
        },
    },
    
    # Rate limiting to avoid overwhelming APIs
    task_annotations={
        'app.tasks.sync_tasks.sync_product_to_woocommerce': {
            'rate_limit': '10/s',  # Max 10 products per second
        },
        'app.tasks.sync_tasks.sync_product_to_odoo': {
            'rate_limit': '10/s',
        },
    },
    
    # Broker connection optimization
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_pool_limit=10,  # Connection pool size
    
    # Memory management
    worker_max_memory_per_child=200000,  # 200MB per worker (restart after)
    
    # Task compression for large payloads
    task_compression='gzip',
    result_compression='gzip',
)

# Optional: Configure Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    'multi-instance-product-sync-every-15-minutes': {
        'task': (
            'app.tasks.scheduled_tasks.'
            'schedule_multi_instance_product_sync'
        ),
        'schedule': 900.0,  # 15 minutes in seconds
    },
    'auto-sync-stock-every-30-minutes': {
        'task': 'app.tasks.scheduled_tasks.auto_sync_stock',
        'schedule': 1800.0,  # 30 minutes in seconds
    },
}

if __name__ == '__main__':
    celery_app.start()
