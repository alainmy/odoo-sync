from contextlib import asynccontextmanager
import json
import logging
from fastapi import FastAPI, HTTPException, Request
from app.api.v1.endpoints.admin_endpoint import router as admin_router
from app.api.v1.endpoints.odoo import router as odoo_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.woocommerce import router as woocommerce_router
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.session import get_session, create_session, lifespan
_logger = logging.getLogger(__name__)

  # Cliente global


app = FastAPI(lifespan=lifespan)

origins = [
    "http://localhost",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MySessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Obtener el session_id enviado por el frontend
        excluded_paths = ["/docs", "/redoc", "/openapi.json"]
        # Filtrar la solicitud según la URL
        if request.url.path in excluded_paths:
            return await call_next(request)
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response
        try:
            # headers = dict(request.headers)
            # _logger.info(f"HEADERS: {headers}")
            # session_id = headers.get("api_session")
            # if not session_id:
            #     raise HTTPException(status_code=401, detail="Session ID not provided in cookies")
            # session = await get_session(request)
            # lang = headers.get("lang", 'en_US')
            # website_id = headers.get("website_id", '1')
            # tz = headers.get("tz", 'Europe/Paris')
            # context = {
            #         "lang": lang,
            #         "tz": tz,
            #         "website_id": int(website_id),
            # }         
            # if not session:
            #     # if not session.is_valid() and session.expiry_date:
            #     #     raise HTTPException(status_code=401, detail="Session expired")
            #     new_session_data = {}
            #     new_session_data["context"] = context
            #     create_session(session_id, new_session_data)     
            # else:
            #     session_data = json.loads(session.data)
            #     session_data["context"].update(context)
            #     await create_session(session_id, session_data)
            response = await call_next(request)
            return response
        except HTTPException as ex:
            response = await call_next(request)
            return response
        except Exception as e:
            # Manejo genérico de excepciones inesperadas
            raise HTTPException(status_code=500, detail=str(e))

# app.add_middleware(MySessionMiddleware)


app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(odoo_router, prefix="/odoo", tags=["odoo"])
app.include_router(woocommerce_router, prefix="/woocommerce", tags=["woocommerce"])
# app.include_router(books_router, prefix="/bookscraping", tags=["bookscraping"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5010, reload=True)
