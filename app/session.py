from contextlib import asynccontextmanager
import json
from redis.asyncio import Redis
from fastapi import Depends, FastAPI, HTTPException, Header, Cookie, Request, Response
# Configuración de la conexión

redis: Redis = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis
    redis = Redis(host="localhost", port=6379, db=0)
    
    try:
        await redis.ping()
        print("✅ Redis conectado correctamente.")
    except Exception as e:
        print(f"❌ Error al conectar con Redis: {e}")
    
    # ⬇️ Ejecuta la app
    yield

    # ⬇️ Cierre limpio de Redis
    await redis.close()
    await redis.connection_pool.disconnect()
    print("🔌 Redis desconectado correctamente.")

async def create_session(uid, data, is_public: bool = False,
                         ACCESS_TOKEN_EXPIRE_MINUTES=60):

    try:
        await redis.set(uid, json.dumps(data))
        await redis.expire(uid,
                           ACCESS_TOKEN_EXPIRE_MINUTES if is_public else 100)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_session(request: Request):

    headers = dict(request.headers)
    session_id = headers.get("api-session")
    if session_id:
        try:
            session = await redis.get(session_id)
            if session:
                return session
            else:
                return None
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(
            status_code=400, detail="Cannot determine session: 'api_session' header is missing"
        )


async def invalidate_session(session_id: str, response: Response):
    if session_id:
        try:
            await redis.delete(session_id)  # Elimina la clave de Redis
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    response.delete_cookie("access_token")  # Elimina la cookie del cliente
    print(f"Session {session_id} invalidated.")
