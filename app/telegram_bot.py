"""
Ejemplo usando python-telegram-bot v20+ (asyncio).
Requisitos:
- pip install python-telegram-bot --upgrade
- pip install httpx
Configura las variables de entorno:
- TELEGRAM_BOT_TOKEN
- FASTAPI_URL (ej: http://localhost:8000/process-pdf)
Añade el bot al grupo. Si quieres que reciba todos mensajes de documento,
desactiva la 'privacy mode' en @BotFather (setprivacy -> disable).
"""
import asyncio
from email import message
import json
import os
import logging
from pickle import GET
import re
from venv import create
import httpx
from rsa import verify
from telegram import Update
from telegram.ext import ApplicationBuilder, \
    ConversationHandler, ContextTypes, MessageHandler, \
    filters, CommandHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8576281658:AAFpJQHngd5jzpwRuAIQJMRUdou1MsXbotY"
FASTAPI_URL = os.getenv(
    "FASTAPI_URL", "https://fastapi.localhost")

CHAT_WEBHOOK_URL = os.getenv(
    "CHAT_WEBHOOK_URL", "http://localhost:5678/webhook-test/f365a6a5-c723-4a6a-a233-41e98dc0903f")
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "60"))

EMAIL, WAIT_PDF = range(2)
EMAIL_USER, GET_USERNAME = range(2)


application = ApplicationBuilder().token(BOT_TOKEN).build()
# ======================
# CONVERSATION FLOW
# ======================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hola, antes de continuar dime tu email:")
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text
    if not re.match(r"[^@]+@[^@]+\.[^@]+", update.message.text):
        await update.message.reply_text("❌ Email inválido, intenta de nuevo:")
        return EMAIL
    await update.message.reply_text("Perfecto ✅ Ahora envíame el PDF 📄")
    return WAIT_PDF


async def get_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        await msg.reply_text("❌ Solo acepto archivos PDF")
        return WAIT_PDF

    # Guardar datos necesarios para responder luego
    context.user_data["chat_id"] = msg.chat_id
    context.user_data["private_chat_id"] = msg.from_user.id
    context.user_data["username"] = msg.from_user.username
    context.user_data["file_id"] = doc.file_id
    context.user_data["filename"] = doc.file_name

    await msg.reply_text(
        "Gracias por enviar tu PDF 📄\n"
        "Para recibir tu resultado final en privado, por favor abre un chat con el bot:\n"
        f"[Abrir chat privado](https://t.me/alain8904bot)",
        parse_mode="Markdown"
    )

    # Procesar en background
    asyncio.create_task(process_pdf(context))

    return ConversationHandler.END


# ======================
# BACKGROUND TASK
# ======================

# ======================
# CREATION OF USER
# ======================

async def crete_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hola, antes de continuar dime tu email:")
    return EMAIL_USER


async def crete_user_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text
    if not re.match(r"[^@]+@[^@]+\.[^@]+", update.message.text):
        await update.message.reply_text("❌ Email inválido, intenta de nuevo:")
        return EMAIL
    await update.message.reply_text("Perfecto ✅ Ahora envíame username 📄")
    return GET_USERNAME


async def crete_user_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):

    username = update.message.text
    telegram_id = update.message.from_user.id
    data = {
        "username": username,
        "telegram_id": telegram_id,
        "email": context.user_data["email"]
    }
    try:
        bot = context.bot
        text = f"👋 Hola {username}, gracias por registrarte.\n\n"
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception as e:
        logger.exception("Error en la creación del usuario")
        await context.bot.send_message(
            chat_id=telegram_id,
            text=f"❌ Error en la creación del usuario: {str(e)}"
        )
    asyncio.create_task(create_user_service(update=update, context=context, data=data))
    return ConversationHandler.END


async def create_user_service(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict):

    try:
        async with httpx.AsyncClient(verify=False) as client:
            headers = {
                "content-type": "application/json",
                "accept": "application/json"
            }
            response = await client.post(
                f"{FASTAPI_URL}/projects/users",
                headers=headers,
                json=data,
                timeout=60,
            )
            if response.status_code != 200:

                await update.message.reply_text(
                    "🤖 Estamos haciendo arreglos en el sistema,. En breve lo atendemos"
                )
            else:
                response.raise_for_status()
                r_json = response.json()
                message_text = f"@{data['username']}, tu usuario ha sido creado con éxito"
                await update.message.reply_text(
                    message_text
                )
    except Exception as e:
        logger(f"Error en la IA:{str(e)}")
        await update.message.reply_text(
            f"🤖 IA (fuera del flujo): recibí tu mensaje. Pero estamos trabjando en el sistema. Por favor intentalo de nuevo más tarde.\n\n"
        )


async def process_pdf(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data["chat_id"]
    private_chat_id = context.user_data["private_chat_id"]
    file_id = context.user_data["file_id"]
    filename = context.user_data["filename"]
    email = context.user_data["email"]
    username = context.user_data["username"]

    try:
        bot = context.bot
        file = await bot.get_file(file_id)
        pdf_bytes = bytes(await file.download_as_bytearray())

        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            files = {"file": (filename, pdf_bytes, "application/pdf")}
            headers = {
                "x-api-key": "supersecretkey",
                "accept": "application/json",
                "private-chat-id": str(private_chat_id),
                "chat-id": str(chat_id),
                'username': f"@{username}"
            }
            resp = await client.post(f"{FASTAPI_URL}/invoice/send-invoice-pdf/", files=files, headers=headers)
            resp.raise_for_status()

            result = resp.json()

        # 🔔 RESPUESTA FINAL AL USUARIO
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ *PDF recivido correctamente*\n\n"
                f"📄 Archivo: `{filename}`\n"
                f"📧 Email: `{email}`\n"
                f"🧾 Cualquierd detalle le responderemos al privado"
            ),
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.exception("Error procesando PDF")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Error procesando tu PDF: {str(e)}"
        )


# ======================
# IA / MENSAJES LIBRES
# ======================

async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text(
            "Si nesesitas ayuda o esta comenzando puedes escribirnos al primavdo a este link https://t.me/alain8904bot"
        )
        return  # evita ruido en grupos

    text = update.message.text

    try:
        async with httpx.AsyncClient(verify=False) as client:
            headers = {
                "User-Agent": "PostmanRuntime/7.36.3",
                "private-chat-id": str(update.message.from_user.id),
                "username": update.message.from_user.username,
                "chat-id": str(update.message.chat.id)
            }
            # Enviar datos al api para que lo procese con la IA que esta en n8n
            # response = await client.post(
            #     f"{FASTAPI_URL}/invoice/telegram-chatter/",
            #     headers=headers,
            #     timeout=60,
            #     params={"message": text},
            # )
            response = await client.post(
                f"{FASTAPI_URL}/projects/chatter/",
                headers=headers,
                timeout=60,
                params={"message": text},
            )
            if response.status_code != 200:

                await update.message.reply_text(
                    "🤖 Estamos haciendo arreglos en el sistema,. En breve lo atendemos"
                )
            else:
                response.raise_for_status()
                r_json = response.json()
                message_text = r_json["message"]
                await update.message.reply_text(
                    message_text
                )
    except Exception as e:
        logger.exception(f"Error en la IA:{str(e)}")
        await update.message.reply_text(
            f"🤖 IA (fuera del flujo): recibí tu mensaje. Pero estamos trabjando en el sistema. Por favor intentalo de nuevo más tarde.\n\n"
        )


# ======================
# Private message handler
# ======================


async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text

    await update.message.reply_text(
        f"🤖 IA (mensaje privado): recibí tu mensaje:\n\n{text}"
    )

    # Guardar datos necesarios para responder luego
    context.user_data["chat_id"] = chat_id
    context.user_data["text"] = text

    return ConversationHandler.END

# ======================
# MAIN
# ======================


def main():

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            WAIT_PDF: [MessageHandler(filters.Document.PDF, get_pdf)],
        },
        fallbacks=[CommandHandler(
            "cancel", lambda u, c: ConversationHandler.END)],
        per_chat=True,
        per_user=True,
    )
    create_user_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("create_user", crete_user_start)],
        states={
            EMAIL_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, crete_user_get_email)],
            GET_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, crete_user_get_username)],
            # CREATE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_user_x)],
        },
        fallbacks=[CommandHandler(
            "cancel", lambda u, c: ConversationHandler.END)],
        per_chat=True,
        per_user=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(create_user_conv_handler)

    # IA fuera del contexto
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_handler)
    )

    logger.info("🤖 Bot iniciado")
    application.run_polling()


if __name__ == "__main__":
    main()
