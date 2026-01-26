import os
from typing import List
import psycopg2
from openai import OpenAI
import tiktoken

# ---------------- CONFIG ----------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
BASE_PROJECTS_PATH = "D:\DOCUMENTS\Proyectos\Odoo\proyectos"

DB_URL = "postgresql://postgres:postgres@woocommerce_odoo_postgres:5432/knowledgebase"

client = OpenAI(api_key="")
# conn = psycopg2.connect(DB_URL)
# cur = conn.cursor()

# ---------------- UTILS ----------------
def chunk_text(text, max_tokens=300):
    encoder = tiktoken.get_encoding("cl100k_base")
    tokens = encoder.encode(text)

    chunks = []
    for i in range(0, len(tokens), max_tokens):
        chunk_tokens = tokens[i:i + max_tokens]
        chunks.append(encoder.decode(chunk_tokens))

    return chunks


def embed(text: str) -> List[float]:
    return client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    ).data[0].embedding


# ---------------- MAIN ----------------
# for project_name in os.listdir(BASE_PROJECTS_PATH):
#     if project_name.startswith("."):
#         continue
#     project_path = os.path.join(BASE_PROJECTS_PATH, project_name)

#     if not os.path.isdir(project_path):
#         continue

#     print(f"📁 Proyecto: {project_name}")

#     # Crear proyecto
#     cur.execute(
#         "INSERT INTO projects (name) VALUES (%s) RETURNING id;",
#         (project_name,)
#     )
#     project_id = cur.fetchone()[0]

#     for root, _, files in os.walk(project_path):
#         for file in files:
#             if not file.endswith((".txt", ".md", ".py")):
#                 continue

#             file_path = os.path.join(root, file)
#             print(f"   📄 Documento: {file}")

#             with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
#                 content = f.read()

#             # Crear documento
#             cur.execute(
#                 "INSERT INTO documents (project_id, title) VALUES (%s, %s) RETURNING id;",
#                 (project_id, file)
#             )
#             document_id = cur.fetchone()[0]

#             chunks = chunk_text(content)

#             for idx, chunk in enumerate(chunks):
#                 embedding = embed(chunk)

#                 cur.execute("""
#                     INSERT INTO document_chunks
#                     (document_id, chunk_index, content, embedding)
#                     VALUES (%s, %s, %s, %s)
#                 """, (document_id, idx, chunk, embedding))

#     conn.commit()

# cur.close()
# conn.close()

print("✅ Importación completada")
