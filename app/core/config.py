from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./test.db"
    secret_key: str = "supersecretkey"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    odoo_url: str = "http://host.docker.internal:8069"
    odoo_db: str = "c4e"
    odoo_username: str = "admin"
    odoo_password: str = "admin"
    wc_base_url: str = "https://host.docker.internal/wp-json/wc/v3"
    wc_consumer_key: str = "ck_eb847e061f9dfc3ddd9a21e3e2eaa23988e41514"
    wc_consumer_secret: str = "cs_61877797f37e8a43aff18da63bbc42c89ba85cf2"
    wc_redis_host: str = "redis"
    wc_redis_port: str = "6379"
    n8n_web_hook_url: str = "http://woocommerce_n8n:5678/webhook-test"

    class Config:
        env_file = "../.env"


settings = Settings()
