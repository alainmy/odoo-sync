"""
Celery tasks package initialization.
"""
from app.tasks.sync_tasks import *
from app.tasks.webhook_tasks import *
from app.tasks.scheduled_tasks import *
from app.tasks.pricelist_tasks import *
from app.tasks.instance_tasks import *
# Import task_monitoring to activate signal handlers
import app.tasks.task_monitoring
