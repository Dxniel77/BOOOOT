"""
bot.py — VERSIÓN OPTIMIZADA
Se corrigió la latencia en botones y se optimizó la respuesta.
"""
import logging
import os
from datetime import datetime

from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db
import messages as msg
import keyboards as kb

# ── Configuración ─────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

# Nivel WARNING para evitar que el procesamiento de logs ralentice a Railway
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.WARNING,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Estados de conversación
S_WAITING_ACTIVATE_CODE, S_WAITING_RENEW_CODE = 10, 11
S_ADMIN_WAITING_GEN, S_ADMIN_WAITING_DEACT = 20, 21

# ── Handlers de Usuario ───────────────────────────────────────────────────────

async def user_entry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sub = db.get_subscription(user.id)
    await update.message.reply_text(
        msg.welcome(user.first_name),
        reply_markup=kb.user_main_menu(bool(sub)),
        parse_mode=ParseMode.MARKDOWN
    )

async def user_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # RESPUESTA INMEDIATA: Quita el reloj de arena del botón al instante
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data

    if data == "u:menu":
        sub = db.get_subscription(user_id)
        await query.edit_message_text(
            msg.menu_user_active() if sub else msg.menu_user_no_sub(),
            reply_markup=kb.user_main_menu(bool(sub)),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "u:status":
        sub = db.get_subscription(user_id)
        if not sub:
            await query.edit_message_text("❌ No tienes suscripción activa.", reply_markup=kb.user_back())
            return
        await query.edit_message_text(msg.user_status(sub), reply_markup=kb.user_status_buttons(), parse_mode=ParseMode.MARKDOWN)

# ── Handlers de Admin ─────────────────────────────────────────────────────────

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("🛠 **Panel de Control Admin**", reply_markup=kb.admin_main_menu(), parse_mode=ParseMode.MARKDOWN)

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID:
        await query.answer("Acceso denegado", show_alert=True)
        return

    await query.answer() # Quita el lag del botón

    data = query.data
    if data in ["a:menu", "a:refresh"]:
        await query.edit_message_text("🛠 **Panel de Control Admin**", reply_markup=kb.admin_main_menu(), parse_mode=ParseMode.MARKDOWN)
    elif data == "a:stats":
        stats = db.get_stats()
        await query.edit_message_text(msg.admin_stats(stats), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    elif data == "a:list":
        codes = db.get_active_codes()
        await query.edit_message_text(msg.admin_codes_list(codes), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ── Procesos de Activación (Conversation) ─────────────────────────────────────

async def start_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔑 **Introduce tu código de acceso:**", reply_markup=kb.user_cancel(), parse_mode=ParseMode.MARKDOWN)
    return S_WAITING_ACTIVATE_CODE

async def process_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_text = update.message.text.strip()
    user = update.effective_user
    
    success, message = db.activate_code(user.id, user.first_name, code_text)
    
    if success:
        try:
            link = await context.bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
            await update.message.reply_text(f"✅ **¡Suscripción Activada!**\n\nÚnete aquí: {link.invite_link}", reply_markup=kb.user_after_success(), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"✅ Código válido, pero hubo un error con el link: {e}")
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"❌ {message}\nPrueba de nuevo o cancela:", reply_markup=kb.user_cancel())
        return S_WAITING_ACTIVATE_CODE

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Cancelado")
    await update.callback_query.edit_message_text("Operación cancelada.", reply_markup=kb.user_main_menu())
    return ConversationHandler.END

# ── Tareas Automáticas ────────────────────────────────────────────────────────

async def job_check_expirations(context: ContextTypes.DEFAULT_TYPE):
