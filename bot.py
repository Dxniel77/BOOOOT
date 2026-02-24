"""
bot.py — OPTIMIZADO PARA VELOCIDAD
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

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

# Reducimos logs para que el servidor no se sature procesando texto
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.WARNING, # Cambiado a WARNING para mayor velocidad
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Estados
S_WAITING_ACTIVATE_CODE, S_WAITING_RENEW_CODE = 10, 11
S_ADMIN_WAITING_GEN, S_ADMIN_WAITING_DEACT = 20, 21

# ── Funciones de Usuario ──────────────────────────────────────────────────────

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
    # LA CLAVE: answer() quita el reloj de arena al instante
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
            await query.edit_message_text("❌ No tienes suscripción.", reply_markup=kb.user_back())
            return
        await query.edit_message_text(
            msg.user_status(sub),
            reply_markup=kb.user_status_buttons(),
            parse_mode=ParseMode.MARKDOWN
        )

# ── Funciones de Admin ────────────────────────────────────────────────────────

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text(
        "🛠 **Panel de Control**",
        reply_markup=kb.admin_main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID: 
        await query.answer("No autorizado", show_alert=True)
        return

    await query.answer() # Confirmación inmediata

    data = query.data
    if data == "a:menu" or data == "a:refresh":
        await query.edit_message_text("🛠 **Panel de Control**", reply_markup=kb.admin_main_menu(), parse_mode=ParseMode.MARKDOWN)
    
    elif data == "a:stats":
        stats = db.get_stats()
        await query.edit_message_text(msg.admin_stats(stats), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    
    elif data == "a:list":
        codes = db.get_active_codes()
        await query.edit_message_text(msg.admin_codes_list(codes), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ── Conversation Handlers (Lógica de entrada de texto) ────────────────────────

async def start_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔑 **Escribe tu código:**", reply_markup=kb.user_cancel(), parse_mode=ParseMode.MARKDOWN)
    return S_WAITING_ACTIVATE_CODE

async def process_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_text = update.message.text.strip()
    user = update.effective_user
    
    success, message = db.activate_code(user.id, user.first_name, code_text)
    
    if success:
        try:
            link = await context.bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
            await update.message.reply_text(f"✅ **¡Activado!**\nEnlace: {link.invite_link}", reply_markup=kb.user_after_success(), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"✅ Código válido, pero error al crear link: {e}")
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"❌ {message}", reply_markup=kb.user_cancel())
        return S_WAITING_ACTIVATE_CODE

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Cancelado")
    await update.callback_query.edit_message_text("Acción cancelada.", reply_markup=kb.user_main_menu())
    return ConversationHandler.END

# ── Job de Limpieza (Optimizado) ──────────────────────────────────────────────

async def job_check_expirations(context: ContextTypes.DEFAULT_TYPE):
    expired = db.get_expired_active()
    for sub in expired:
        try:
            await context.bot.ban_chat_member(CHANNEL_ID, sub['user_id'])
            await context.bot.unban_chat_member(CHANNEL_ID, sub['user_id'])
            db.mark_expired(sub['id'])
            await context.bot.send_message(sub['user_id'], "🔴 Tu suscripción ha vencido y has sido removido del canal.")
        except:
            pass

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # User Conv
    user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_activation, pattern="^u:activate_start$")],
        states={S_WAITING_ACTIVATE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_activation)]},
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern="^u:cancel$")],
    )

    app.add_handler(CommandHandler("start", user_entry_start))
    app.add_handler(CommandHandler("admin", admin_entry))
    app.add_handler(user_conv)
    app.add_handler(CallbackQueryHandler(user_callbacks, pattern="^u:"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^a:"))

    app.job_queue.run_repeating(job_check_expirations, interval=3600, first=10)

    print("🚀 Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()
