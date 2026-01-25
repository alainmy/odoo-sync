"""
Example main.py update to use new Celery-enabled endpoints.

To activate the new Celery endpoints, update your main.py file.
"""

# ============================================================================
# BEFORE (Old synchronous endpoints)
# ============================================================================
"""
from app.api.v1.endpoints import woocommerce

app.include_router(woocommerce.router, prefix="/api/v1")
"""

# ============================================================================
# AFTER (New Celery-enabled endpoints)
# ============================================================================
"""
from app.api.v1.endpoints import woocommerce_celery

app.include_router(woocommerce_celery.router, prefix="/api/v1")
"""

# ============================================================================
# GRADUAL MIGRATION (Both endpoints available)
# ============================================================================
"""
from app.api.v1.endpoints import woocommerce, woocommerce_celery

# Old endpoints at /api/v1/woocommerce/*
app.include_router(woocommerce.router, prefix="/api/v1")

# New endpoints at /api/v1/woocommerce-async/*
app.include_router(woocommerce_celery.router, prefix="/api/v1/woocommerce-async", tags=["woocommerce-async"])
"""

# ============================================================================
# FULL EXAMPLE: Updated main.py
# ============================================================================

"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
from app.session import redis_client, redis_connect, redis_disconnect

# Import routers
from app.api.v1.endpoints import (
    admin_endpoint,
    auth,
    odoo,
    woocommerce_celery,  # NEW: Celery-enabled endpoints
    proccess_invoice,
    projects_router
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to Redis
    await redis_connect()
    yield
    # Shutdown: Close Redis connection
    await redis_disconnect()


app = FastAPI(
    title="WooCommerce-Odoo Sync API",
    description="Microservice for synchronizing WooCommerce and Odoo with Celery",
    version="2.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(admin_endpoint.router, prefix="/api/v1", tags=["admin"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(odoo.router, prefix="/api/v1", tags=["odoo"])

# NEW: Celery-enabled WooCommerce endpoints
app.include_router(woocommerce_celery.router, prefix="/api/v1", tags=["woocommerce"])

app.include_router(proccess_invoice.router, prefix="/api/v1", tags=["invoices"])
app.include_router(projects_router.router, prefix="/api/v1", tags=["projects"])


@app.get("/")
async def root():
    return {
        "message": "WooCommerce-Odoo Sync API with Celery",
        "version": "2.0.0",
        "docs": "/docs",
        "flower": "http://localhost:5555"
    }


@app.get("/health")
async def health_check():
    # Check Redis connection
    try:
        await redis_client.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"
    
    return {
        "status": "healthy",
        "redis": redis_status,
        "celery": "check Flower dashboard at http://localhost:5555"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5010)
"""
