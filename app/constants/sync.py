"""Constants for sync operations."""

from enum import Enum


class SyncStatus:
    """Sync status constants."""
    NEVER_SYNCED = "never_synced"
    SYNCED = "synced"
    MODIFIED = "modified"
    ERROR = "error"
    PENDING = "pending"


class SyncAction:
    """Sync action constants."""
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    ERROR = "error"
    DELETED = "deleted"


class WebhookStatus:
    """Webhook processing status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class TaskStatus:
    """Celery task status constants."""
    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"


class SyncDirection:
    """Sync direction constants."""
    ODOO_TO_WC = "odoo_to_wc"
    WC_TO_ODOO = "wc_to_odoo"
    BIDIRECTIONAL = "bidirectional"


class SyncMode:
    """Sync mode constants."""
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
