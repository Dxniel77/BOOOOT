"""
bot.py — Bot de Suscripción v3
=================================
CORRECCIONES Y OPTIMIZACIONES:
  ✅ query.answer() SIEMPRE como primera línea en callbacks (elimina el círculo de carga)
  ✅ ConversationHandler con fallbacks que responden TODOS los botones fuera de estado
  ✅ Limpieza automática: si el usuario presiona un botón de menú durante una conversación,
     la conversación se cancela y se abre el menú solicitado
  ✅ Jobs con aiosqlite (no bloquean el event loop)
  ✅ Logging optimizado para producción (httpx en WARNING, telegram en WARNING)
  ✅ Timeouts de conversación (ConversationHandler.WAITING_STATE no queda atascado)
"""

import logging
import os
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

import database as db
import keyboards as kb
import messages as msg

# ── Logging optimizado para producción ──────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
# Silenciar librerías muy verbosas — reduce CPU en producción
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ── Variables de entorno ────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

# ── Estados de ConversationHandler ──────────────────────────────────────────
WAITING_ACTIVATE_CODE  = 1
WAITING_RENEW_CODE     = 2
WAITING_GEN_CODE       = 3
WAITING_DEACTIVATE     = 4
WAITING_CONFIRM_DEACT  = 5


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

async def safe_answer(query, text: str = None, show_alert: bool = False) -> None:
    """Llama a query.answer() sin lanzar excepción si ya expiró."""
    try:
        await query.answer(text=text, show_alert=show_alert)
    except TelegramError:
        pass


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envía o edita el mensaje con el menú principal."""
    text = msg.WELCOME
    markup = kb.main_menu_keyboard()
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            await update.effective_chat.send_message(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.effective_chat.send_message(
            text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
        )


# ════════════════════════════════════════════════════════════════════════════
#  /start y menú principal
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update, context)


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botón 🏠 Menú principal — cierra cualquier conversación activa."""
    query = update.callback_query
    await safe_answer(query)  # ← SIEMPRE primero: libera el botón instantáneamente
    await send_main_menu(update, context)
    return ConversationHandler.END  # cierra conversación si estaba en una


async def my_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    subscription = await db.get_subscription(query.from_user.id)
    if not subscription:
        text = msg.NO_SUBSCRIPTION
    else:
        text = msg.subscription_status(subscription)

    try:
        await query.edit_message_text(
            text,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(
            text,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


async def contact_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    try:
        await query.edit_message_text(
            msg.CONTACT_ADMIN,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ACTIVAR CÓDIGO (ConversationHandler)
# ════════════════════════════════════════════════════════════════════════════

async def activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    try:
        await query.edit_message_text(
            msg.ENTER_CODE,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.ENTER_CODE, parse_mode=ParseMode.MARKDOWN)
    return WAITING_ACTIVATE_CODE


async def activate_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    user = update.effective_user
    days = await db.use_code(code, user.id, user.username or "", user.full_name)

    if days is None:
        await update.message.reply_text(
            msg.CODE_NOT_FOUND,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_ACTIVATE_CODE  # dejar en estado para reintentar

    # Obtener link de invitación al canal
    try:
        link = await context.bot.create_chat_invite_link(
            CHANNEL_ID, member_limit=1, expire_date=datetime.now() + timedelta(hours=24)
        )
        invite_url = link.invite_link
    except TelegramError as e:
        logger.error("Error creando invite link: %s", e)
        invite_url = None

    sub = await db.get_subscription(user.id)
    expires_str = msg.fmt_date(sub["expires_at"]) if sub else "?"

    text = msg.CODE_SUCCESS.format(days=days, expires_at=expires_str)
    if invite_url:
        text += f"\n\n🔗 [Acceder al canal]({invite_url})"

    await update.message.reply_text(
        text,
        reply_markup=kb.back_to_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )

    # Notificar al admin
    try:
        await context.bot.send_message(
            ADMIN_ID,
            msg.admin_new_activation(user.id, user.username or "", user.full_name, days),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass

    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  RENOVAR CÓDIGO (ConversationHandler)
# ════════════════════════════════════════════════════════════════════════════

async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    try:
        await query.edit_message_text(
            msg.ENTER_CODE_RENEW,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.ENTER_CODE_RENEW)
    return WAITING_RENEW_CODE


async def renew_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    user = update.effective_user
    days = await db.use_code(code, user.id, user.username or "", user.full_name)

    if days is None:
        await update.message.reply_text(
            msg.CODE_NOT_FOUND,
            reply_markup=kb.back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_RENEW_CODE

    sub = await db.get_subscription(user.id)
    expires_str = msg.fmt_date(sub["expires_at"]) if sub else "?"

    await update.message.reply_text(
        msg.CODE_RENEWED.format(days=days, expires_at=expires_str),
        reply_markup=kb.back_to_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        await context.bot.send_message(
            ADMIN_ID,
            msg.admin_new_activation(user.id, user.username or "", user.full_name, days),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass

    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  PANEL ADMIN
# ════════════════════════════════════════════════════════════════════════════

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    await update.effective_chat.send_message(
        msg.ADMIN_WELCOME,
        reply_markup=kb.admin_panel_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón
    try:
        await query.edit_message_text(
            msg.ADMIN_WELCOME,
            reply_markup=kb.admin_panel_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(
            msg.ADMIN_WELCOME,
            reply_markup=kb.admin_panel_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


async def admin_list_codes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    codes = await db.list_active_codes()
    text  = msg.admin_list_codes(codes)
    try:
        await query.edit_message_text(
            text,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    stats = await db.get_stats()
    try:
        await query.edit_message_text(
            msg.admin_stats_msg(stats),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    stats = await db.get_stats()
    text  = (
        f"👥 *Usuarios activos:* {stats.get('active_subs', 0)}\n"
        f"⚠️ *Por vencer (3 días):* {stats.get('expiring_soon', 0)}"
    )
    try:
        await query.edit_message_text(
            text,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


async def admin_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query, "✅ Panel actualizado")  # ← libera el botón con mensaje

    try:
        await query.edit_message_text(
            msg.ADMIN_WELCOME,
            reply_markup=kb.admin_panel_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ── Admin: Generar código ────────────────────────────────────────────────────

async def admin_gen_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    try:
        await query.edit_message_text(
            msg.admin_gen_code_prompt(),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.admin_gen_code_prompt(), parse_mode=ParseMode.MARKDOWN)
    return WAITING_GEN_CODE


async def admin_gen_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            msg.ADMIN_CODE_INVALID,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_GEN_CODE

    code = parts[0].upper()
    try:
        days     = int(parts[1])
        max_uses = int(parts[2]) if len(parts) >= 3 else 1
    except ValueError:
        await update.message.reply_text(
            msg.ADMIN_CODE_INVALID,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_GEN_CODE

    created = await db.create_code(code, days, max_uses)
    if not created:
        await update.message.reply_text(
            msg.ADMIN_CODE_EXISTS,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_GEN_CODE

    await update.message.reply_text(
        msg.admin_code_created(code, days, max_uses),
        reply_markup=kb.back_to_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── Admin: Desactivar código ─────────────────────────────────────────────────

async def admin_deactivate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    try:
        await query.edit_message_text(
            msg.ADMIN_ENTER_DEACTIVATE,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.ADMIN_ENTER_DEACTIVATE)
    return WAITING_DEACTIVATE


async def admin_deactivate_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    context.user_data["pending_deactivate"] = code
    await update.message.reply_text(
        msg.admin_confirm_deactivate(code),
        reply_markup=kb.confirm_deactivate_keyboard(code),
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAITING_CONFIRM_DEACT


async def admin_confirm_deactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón

    code = query.data.split(":", 1)[1] if ":" in query.data else ""
    if code:
        await db.deactivate_code(code)
        text = msg.admin_deactivated(code)
    else:
        text = "❌ Error al identificar el código."

    try:
        await query.edit_message_text(
            text,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  FALLBACK UNIVERSAL — responde botones "muertos" durante una conversación
# ════════════════════════════════════════════════════════════════════════════

async def fallback_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Se ejecuta cuando el usuario presiona un botón de menú mientras está
    dentro de un ConversationHandler en otro estado.
    Cancela la conversación y redirige al destino del botón.
    """
    query = update.callback_query
    await safe_answer(query)  # ← libera el botón inmediatamente

    data = query.data

    # Redirigir al destino correcto
    if data == "main_menu":
        await send_main_menu(update, context)
    elif data == "my_sub":
        return await my_subscription_callback(update, context)
    elif data == "contact_admin":
        return await contact_admin_callback(update, context)
    elif data == "admin_back":
        return await admin_back_callback(update, context)
    else:
        # Botón desconocido durante conversación → cancelar y volver al menú
        try:
            await query.edit_message_text(
                msg.CANCEL,
                reply_markup=kb.back_to_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            pass

    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comando /cancel o timeout — cancela cualquier conversación activa."""
    if update.callback_query:
        await safe_answer(update.callback_query)
    try:
        if update.effective_message:
            await update.effective_message.reply_text(
                msg.CANCEL,
                reply_markup=kb.back_to_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  JOBS AUTOMÁTICOS
# ════════════════════════════════════════════════════════════════════════════

async def job_check_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Expulsa usuarios con suscripción vencida."""
    expired = await db.get_expired_subscriptions()
    for sub in expired:
        user_id = sub["user_id"]
        try:
            await context.bot.ban_chat_member(CHANNEL_ID, user_id)
            await context.bot.unban_chat_member(CHANNEL_ID, user_id)  # permite volver si renueva
        except TelegramError as e:
            logger.warning("No se pudo expulsar a %s: %s", user_id, e)

        try:
            await context.bot.send_message(
                user_id,
                msg.SUBSCRIPTION_EXPIRED,
                reply_markup=kb.main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            pass

        await db.delete_subscription(user_id)
        logger.info("Suscripción expirada eliminada: user_id=%s", user_id)


async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Avisa a usuarios que vencen en 3 días."""
    expiring = await db.get_expiring_soon(days=3)
    for sub in expiring:
        user_id = sub["user_id"]
        try:
            expiry   = datetime.fromisoformat(sub["expires_at"])
            days_left = max(0, (expiry - datetime.now()).days)
            await context.bot.send_message(
                user_id,
                msg.warn_expiring(days_left),
                reply_markup=kb.main_menu_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            await db.mark_warned(user_id)
        except TelegramError as e:
            logger.warning("No se pudo avisar a %s: %s", user_id, e)


# ════════════════════════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DE LA APLICACIÓN
# ════════════════════════════════════════════════════════════════════════════

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Fallbacks comunes para todos los ConversationHandlers ──────────────
    # Cualquier botón de menú cancela la conversación activa
    common_fallbacks = [
        CallbackQueryHandler(main_menu_callback,   pattern="^main_menu$"),
        CallbackQueryHandler(fallback_menu_button, pattern="^(my_sub|contact_admin|activate|renew|admin_back|admin_stats|admin_list_codes|admin_users|admin_refresh|admin_gen_code|admin_deactivate)$"),
        CommandHandler("cancel", cancel_conversation),
        CommandHandler("start",  cancel_conversation),  # /start siempre cancela y va al menú
    ]

    # ── ConversationHandler: Activar código ───────────────────────────────
    activate_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(activate_start, pattern="^activate$")],
        states={
            WAITING_ACTIVATE_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, activate_receive_code),
            ],
        },
        fallbacks=common_fallbacks,
        conversation_timeout=300,  # 5 min sin respuesta → cancela automáticamente
    )

    # ── ConversationHandler: Renovar ──────────────────────────────────────
    renew_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
        states={
            WAITING_RENEW_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, renew_receive_code),
            ],
        },
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin generar código ─────────────────────────
    admin_gen_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_gen_code_start, pattern="^admin_gen_code$")],
        states={
            WAITING_GEN_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gen_code_receive),
            ],
        },
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin desactivar código ──────────────────────
    admin_deact_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_deactivate_start, pattern="^admin_deactivate$")],
        states={
            WAITING_DEACTIVATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deactivate_receive),
            ],
            WAITING_CONFIRM_DEACT: [
                CallbackQueryHandler(admin_confirm_deactivate_callback, pattern="^admin_confirm_deactivate:"),
                CallbackQueryHandler(admin_back_callback, pattern="^admin_back$"),
            ],
        },
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── Registrar handlers ────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(activate_conv)
    app.add_handler(renew_conv)
    app.add_handler(admin_gen_conv)
    app.add_handler(admin_deact_conv)

    # Handlers simples (no necesitan conversación)
    app.add_handler(CallbackQueryHandler(main_menu_callback,         pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(my_subscription_callback,   pattern="^my_sub$"))
    app.add_handler(CallbackQueryHandler(contact_admin_callback,     pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(admin_back_callback,        pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_list_codes_callback,  pattern="^admin_list_codes$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback,       pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users_callback,       pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_refresh_callback,     pattern="^admin_refresh$"))

    # ── Jobs ──────────────────────────────────────────────────────────────
    jq = app.job_queue
    jq.run_repeating(job_check_expired,  interval=3600,  first=60)   # cada hora
    jq.run_repeating(job_warn_expiring,  interval=43200, first=120)  # cada 12h

    return app


async def post_init(app: Application) -> None:
    await db.init_db()
    logger.info("Bot iniciado correctamente.")


def main() -> None:
    app = build_application()
    app.post_init = post_init
    logger.info("Iniciando bot...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        # ✅ FIX: descarta updates acumulados al arrancar.
        # Evita el error Conflict cuando había otra instancia corriendo
        # (ej: pruebas locales + Railway al mismo tiempo).
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
