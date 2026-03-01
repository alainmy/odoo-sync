"""Celery tasks for pricelist synchronization."""
import logging
from typing import Any, Dict
from celery import Task

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.tasks.sync_helpers import create_wc_api_client
from app.models.admin import WooCommerceInstance
from app.repositories.webhook_config_repository import WebhookConfigRepository
from app.schemas.webhook_schemas import WebhookConfigCreate
from app.services.webhook_service import WebhookService
from app.tasks.task_monitoring import update_task_progress

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management."""
    _db = None

    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="app.tasks.instance_tasks.create_wwc_webhooks_for_instance",
    max_retries=3,
    default_retry_delay=60
)
def create_wwc_webhooks_for_instance(
        self,
        config: Dict[str, Any],
        new_webhook_id: int,
        instance_id: int) -> None:
    """Crear webhooks para una instancia (ejemplo para productos)"""

    try:
        # Initialize services and repositories
        service, repo = setup_services_and_repo(self.db, config)

        # Fetch WooCommerce Instance and set up the API client
        instance = get_woocommerce_instance(self.db, instance_id)
        wcapi = create_wc_api_client(setup_wc_config(instance))

        # Interact with WooCommerce API and handle responses
        handle_webhook_creation(self, service, repo,
                                wcapi, config, new_webhook_id)

    except Exception as e:
        logger.error(f"Exception encountered: {e}")
        raise  # re-raise exception after logging


# Maintain the auxiliary functions for modularization

def setup_services_and_repo(db, config):
    """Setup services and repository instances."""
    config = WebhookConfigCreate(**config)
    service = WebhookService(db)
    repo = WebhookConfigRepository(db)
    return service, repo


def setup_wc_config(instance):
    """Prepare WooCommerce configuration."""
    return {
        "url": instance.woocommerce_url,
        "consumer_key": instance.woocommerce_consumer_key,
        "consumer_secret": instance.woocommerce_consumer_secret
    }


def get_woocommerce_instance(db, instance_id):
    """Retrieve WooCommerce instance by ID."""
    return db.query(WooCommerceInstance).filter(
        WooCommerceInstance.id == instance_id).first()


def handle_webhook_creation(task, service, repo, wcapi, config, new_webhook_id):
    """Create a webhook in WooCommerce and manage local updates."""
    update_task_progress(task, current=2, total=5,
                         message="Creating webhook in WooCommerce...")
    
    config = WebhookConfigCreate(**config)
    wc_response = service.create_webhook_in_woocommerce(wcapi, config)

    if wc_response and wc_response.get('id'):
        process_successful_webhook_creation(
            repo, new_webhook_id, wc_response, task)
    else:
        process_failed_webhook_creation(repo, new_webhook_id, task)


def process_successful_webhook_creation(repo, new_webhook_id, wc_response, task):
    """Process actions after successful webhook creation."""
    repo.update_wc_webhook_id(new_webhook_id, wc_response.get('id'))
    new_webhook = repo.get_by_id(new_webhook_id)
    task.db.refresh(new_webhook)
    logger.info(
        f"Created webhook in WooCommerce with ID {wc_response.get('id')}")
    update_task_progress(task, current=3, total=5,
                         message="Webhook created in WooCommerce successfully.")
    return {
        "success": True,
        "action": "create",
        "odoo_id": new_webhook.id,
        "woocommerce_id": wc_response.get('id'),
        "message": f"Webhook created in WooCommerce with ID {wc_response.get('id')}"
    }


def process_failed_webhook_creation(repo, new_webhook_id, task):
    """Process actions if webhook creation fails."""
    logger.warning(f"Removing webhook {new_webhook_id}")
    repo.delete(new_webhook_id)
    logger.warning(
        "Webhook created locally but failed to create in WooCommerce")
    update_task_progress(task, current=2, total=5,
                         message="Failed to create webhook in WooCommerce.")
    return {
        "success": False,
        "action": "create",
        "odoo_id": new_webhook_id,
        "woocommerce_id": None,
        "message": "Webhook created locally but failed to create in WooCommerce"
    }
