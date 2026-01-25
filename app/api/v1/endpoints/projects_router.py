

import json
from typing import Optional
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request, Depends
from sqlalchemy.orm import Session
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
from app.telegram_bot import application as app
from app.cargar_conocimiento import EMBEDDING_MODEL, embed
from app.schemas.knowledgebase import UserCreate
from app.auth.oauth2 import get_current_user
from app.models.admin import Admin
from app.db.session import get_db
from app.core.config import settings

DB_URL = "postgresql://postgres:postgres@woocommerce_odoo_postgres:5432/knowledgebase"
router = APIRouter()
# TODO: Mover OpenAI API key a variables de entorno
client = OpenAI(api_key=settings.openai_api_key if hasattr(settings, 'openai_api_key') else "")

# ==========================#
#         Projects         #
# ==========================#


@router.get("/projects", summary="Consultar proyectos en la base de datos")
async def get_projects(
    request: Request,
    name: Optional[str] = Query(
        None, description="Filtrar por nombre de proyecto"),
    limit: int = Query(
        100, ge=1, le=100, description="Limite de proyectos a retornar"),
    offset: int = Query(
        0, ge=0,
        description="Offset de proyectos a retornar"),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Consultar proyectos con autenticación y protección contra SQL injection"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # FIX SQL INJECTION: Usar consultas parametrizadas
    if name:
        query = "SELECT id, name FROM projects WHERE name LIKE %s LIMIT %s OFFSET %s"
        cur.execute(query, (f"%{name}%", limit, offset))
    else:
        query = "SELECT id, name FROM projects LIMIT %s OFFSET %s"
        cur.execute(query, (limit, offset))
    
    projects = cur.fetchall()
    conn.close()
    return projects


@router.get("/projects/{project_id}", summary="Consultar proyecto en la base de datos")
async def get_project(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Consultar proyecto específico con protección contra SQL injection"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # FIX SQL INJECTION: Usar consultas parametrizadas
    query = "SELECT id, name FROM projects WHERE id = %s"
    cur.execute(query, (project_id,))
    
    project = cur.fetchone()
    conn.close()
    return project

# ==========================#
#         Documents        #
# ==========================#
# @router.get("/{project_id}/documents")
# def get(
#     request: Request,

# )


# ==========================#
#         Chatter          #
# ==========================#

@router.post("/users", summary="Dar de alta al usuario")
async def user(
    request: Request,
    data: UserCreate = Body(...),
    db: Session = Depends(get_db),
    current_user: Admin = Depends(get_current_user)
):
    """Crear usuario con autenticación requerida"""
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO users (username, telegram_id, email) VALUES (%s, %s, %s) RETURNING id;
        """, (data.username, data.telegram_id, data.email))
        # user_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return {"user_id": 0}
    except Exception as e:
        print(e)
        conn.close()
        return {"error": str(e)}
# ==========================#
#         Chatter          #
# ==========================#


def get_conn():
    return psycopg2.connect(DB_URL)


def to_pgvector(vec):
    return f"[{','.join(map(str, vec))}]"


def search_relevant_chunks(query_embedding, limit=10):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query_embedding_pg = to_pgvector(query_embedding)
    cur.execute("""
        SELECT
            dc.content,
            d.title AS document_title,
            p.name AS project_name
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        JOIN projects p ON p.id = d.project_id
        ORDER BY dc.embedding <-> %s
        LIMIT %s
    """, (query_embedding_pg, limit))

    results = cur.fetchall()
    conn.close()
    return results


def build_context(chunks, last_messages=[]):
    context = []
    for c in chunks:
        context.append(
            f"[Proyecto: {c['project_name']} | Documento: {c['document_title']}]\n{c['content']}"
        )
    for lm in last_messages:
        context.append(lm['content'])
    return "\n\n".join(context)


def ask_ai(message: str, context: str):
    system_prompt = """
        Eres un asistente experto en gestión de proyectos.

        DEBES responder ÚNICAMENTE con un objeto JSON válido.
        NO incluyas texto adicional, comentarios, markdown ni explicaciones.
        NO uses bloques de código.
        NO escribas nada fuera del JSON.

        El usuario te preguntará sobre un proyecto y tú responderás de forma corta y concisa,
        basándote EXCLUSIVAMENTE en el contexto proporcionado.

        El formato de salida DEBE ser exactamente este:

        {
        "user": "<texto del usuario>",
        "answer": "<respuesta concisa>",
        "summary": {
            "text: <resumen del proyecto>",
            "files": [
                {
                    "name": "<nombre del fichero>",
                }
            ]
        }
        }

        Si no sabes la respuesta, indícalo claramente en el campo "answer".

        """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            # {"role": "user", "content": f"CONTEXTO:\n{context}"},
            {"role": "user", "content": (
                f"CONTEXTO DEL PROYECTO:\n"
                f"{context}\n\n"
                f"PREGUNTA DEL USUARIO:\n"
                f"{message}\n\n"
                "INSTRUCCIONES:\n"
                "- Analiza el contexto paso a paso\n"
                "- Extrae conclusiones claras\n"
                "- Relaciona la respuesta con el proyecto\n"
            )},
        ]
    )

    return response.choices[0].message.content


def save_chat(user_id: int, role: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_history (user_id, role, content)
        VALUES (%s, %s, %s)
    """, (user_id, role, content))
    conn.commit()
    conn.close()


def search_last_messages(user_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # FIX SQL INJECTION: Usar consultas parametrizadas
    query = "SELECT content FROM chat_history WHERE user_id = %s ORDER BY id DESC LIMIT 1"
    cur.execute(query, (user_id,))
    last_messages = cur.fetchall()
    conn.close()
    return last_messages


@router.post("/chatter/", summary="Enviar mensaje a chat en n8n", tags=["project chatter"])
async def send_chat_message(
    request: Request,
    message: str = None,
):

    if not message:
        raise HTTPException(status_code=400, detail="Mensaje requerido")

    user_id = request.headers.get("private-chat-id", 1)  # ajusta según tu auth
    username = request.headers.get("username", 1).lower()
    # buscar usuario por el username
    con = get_conn()
    cur = con.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id,username,telegram_id FROM users WHERE telegram_id = %s
    """, (int(user_id),))
    user = cur.fetchone()
    con.commit()
    if not user:
        text = "Usted no se encuentra registrado.\n Por favor dese de alta con el comando /alta"
        try:
            await app.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            print(e)
            return

    # 1️⃣ Buscar contexto
    last_messages = search_last_messages(user["id"])
    # 1️⃣ Embedding del mensaje
    last_messages = last_messages[0]["content"]
    query_embedding = embed(message + last_messages)

    # 2️⃣ Buscar contexto
    chunks = search_relevant_chunks(query_embedding)

    
    # 3️⃣ Construir contexto
    context = build_context(chunks)

    # 4️⃣ Guardar mensaje usuario
    # save_chat(user["id"], "user", message)

    # 5️⃣ Preguntar a la IA
    answer = ask_ai(message, context)
    answer_json = json.loads(answer)
    answer_result = answer_json["answer"]
    summary = json.dumps(answer_json["summary"])

    # 6️⃣ Guardar respuesta IA
    save_chat(user["id"], "assistant", summary)

    return {
        "message": answer_result,
        "sources": chunks
    }
