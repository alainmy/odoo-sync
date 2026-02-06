import fastapi
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./test.db"
    secret_key: str = "supersecretkey"
    fastapi_secret_key: str = "supersecretkey"
    fastapi_debug: bool = True
    fastapi_api_host: str = "http://localhost:8000"
    image_dir: str = "app/images/products"
    fastapi_database: str = "fastapi_db"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    odoo_url: str = "http://host.docker.internal:8069"
    odoo_db: str = "c4e"
    odoo_username: str = "admin"
    odoo_password: str = "admin"
    wc_base_url: str = "http://host.docker.internal:8000/wp-json/wc/v3"
    wc_consumer_key: str = "ck_eb847e061f9dfc3ddd9a21e3e2eaa23988e41514"
    wc_consumer_secret: str = "cs_61877797f37e8a43aff18da63bbc42c89ba85cf2"
    wc_redis_host: str = "woocommerce_redis"
    wc_redis_port: str = "6379"
    n8n_database: str = "n8n_db"
    n8n_basic_auth_user: str = "n8n_admin"
    n8n_basic_auth_password: str = "n8n_password"
    timezone: str = "America/Havana"
    n8n_web_hook_url: str = "http://woocommerce_n8n:5678/webhook-test"
    n8n_webhook_url: str = "http://woocommerce_n8n:5678/webhook-test"

    # Celery Configuration
    celery_broker_url: str = "redis://woocommerce_redis:6379/1"
    celery_result_backend: str = "redis://woocommerce_redis:6379/1"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: list = ["json"]
    celery_timezone: str = "UTC"
    celery_enable_utc: bool = True
    
    # Celery Performance Tuning
    celery_worker_concurrency: int = 4
    celery_worker_prefetch_multiplier: int = 4
    celery_worker_max_tasks_per_child: int = 100
    celery_worker_max_memory_per_child: int = 200000  # 200MB in KB

    # Webhook Configuration
    wc_webhook_secret: str = "your-webhook-secret-key"

    # WooCommerce API Configuration
    wc_api_version: str = "wc/v3"
    wc_request_timeout: int = 60
    wc_verify_ssl: bool = False
    wc_default_per_page: int = 100
    wc_max_per_page: int = 100

    # Celery Retry Configuration
    celery_default_max_retries: int = 3
    celery_default_retry_delay: int = 60
    celery_exponential_backoff_base: int = 2
    celery_max_retry_delay: int = 300

    # Sync Configuration
    sync_batch_size: int = 50
    sync_max_concurrent_tasks: int = 5
    sync_default_product_status: str = "publish"
    
    # API Pagination Configuration
    api_default_limit: int = 50
    api_max_limit: int = 200
    
    # Logging Configuration
    log_sql_queries: bool = False
    log_api_requests: bool = True
    
    # Alert System Configuration
    alerts_enabled: bool = True
    
    # Email Alerts
    alert_email_enabled: bool = False
    alert_email_smtp_host: str = "smtp.gmail.com"
    alert_email_smtp_port: int = 587
    alert_email_smtp_user: str = ""
    alert_email_smtp_password: str = ""
    alert_email_from: str = "alerts@woocommerce-odoo.local"
    alert_email_to: list = []
    
    # Slack Alerts
    alert_slack_enabled: bool = False
    alert_slack_webhook_url: str = ""
    
    # Telegram Alerts
    alert_telegram_enabled: bool = False
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    
    # Webhook Alerts
    alert_webhook_enabled: bool = False
    alert_webhook_url: str = ""
    
    # Flower Monitoring
    flower_user: str = "admin"
    flower_password: str = "admin123"

    wordpress_db_user: str = "admin"
    wordpress_db_password: str = "admin_password"
    wordpress_db_host: str = "mysql"
    wordpress_db_name: str = "woocommerce_db"

    mysql_user: str = "root"
    mysql_password: str = "root_password"
    mysql_database: str = "admin_db"
    mysql_root_password: str = "root_password"

    class Config:
        env_file = "./.env"


settings = Settings()
