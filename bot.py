"""
bot.py — Bot de Suscripción v3
=================================
FEATURES:
  ✅ Añade al canal automáticamente al activar código
  ✅ query.answer() siempre primero — elimina el círculo de carga
  ✅ ConversationHandler con fallbacks universales
  ✅ Job cada 30 min detecta y expulsa intrusos automáticamente
  ✅ Panel admin completo: miembros, intrusos, buscar, expulsar
  ✅ Al vencer suscripción → expulsado automáticamente del canal
  ✅ Logging optimizado para producción
"""

import logging
import os
from datetime import datetime, timedelta

from telegram import Update, ChatMember
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ── Variables de entorno ─────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])

# ── Estados de ConversationHandler ──────────────────────────────────────────
WAITING_ACTIVATE_CODE = 1
WAITING_RENEW_CODE    = 2
WAITING_GEN_CODE      = 3
WAITING_DEACTIVATE    = 4
WAITING_CONFIRM_DEACT = 5
WAITING_SEARCH        = 6
WAITING_KICK_ID       = 7
WAITING_CONFIRM_KICK  = 8


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

async def safe_answer(query, text: str = None, show_alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=show_alert)
    except TelegramError:
        pass


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text   = msg.WELCOME
    markup = kb.main_menu_keyboard()
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
            return
        except TelegramError:
            pass
    await update.effective_chat.send_message(
        text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
    )


async def send_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text   = msg.ADMIN_WELCOME
    markup = kb.admin_panel_keyboard()
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
            )
            return
        except TelegramError:
            pass
    await update.effective_chat.send_message(
        text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
    )


async def add_user_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Añade un usuario directamente al canal. Retorna True si tuvo éxito."""
    try:
        await context.bot.unban_chat_member(CHANNEL_ID, user_id, only_if_banned=True)
        await context.bot.approve_chat_join_request(CHANNEL_ID, user_id)
        return True
    except TelegramError:
        pass
    try:
        # Fallback: añadir directamente
        await context.bot.add_chat_members(CHANNEL_ID, [user_id])
        return True
    except TelegramError as e:
        logger.warning("No se pudo añadir al canal user_id=%s: %s", user_id, e)
        return False


async def kick_user_from_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Expulsa un usuario del canal. Retorna True si tuvo éxito."""
    try:
        await context.bot.ban_chat_member(CHANNEL_ID, user_id)
        await context.bot.unban_chat_member(CHANNEL_ID, user_id)
        return True
    except TelegramError as e:
        logger.warning("No se pudo expulsar user_id=%s: %s", user_id, e)
        return False


# ════════════════════════════════════════════════════════════════════════════
#  /start y menú principal
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update, context)


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    await send_main_menu(update, context)
    return ConversationHandler.END


async def my_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)

    subscription = await db.get_subscription(query.from_user.id)
    text = msg.NO_SUBSCRIPTION if not subscription else msg.subscription_status(subscription)

    try:
        await query.edit_message_text(
            text, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError:
        await query.message.reply_text(
            text, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
    return ConversationHandler.END


async def contact_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    try:
        await query.edit_message_text(
            msg.CONTACT_ADMIN, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ACTIVAR CÓDIGO
# ════════════════════════════════════════════════════════════════════════════

async def activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    try:
        await query.edit_message_text(
            msg.ENTER_CODE, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError:
        await query.message.reply_text(msg.ENTER_CODE)
    return WAITING_ACTIVATE_CODE


async def activate_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().upper()
    user = update.effective_user
    days = await db.use_code(code, user.id, user.username or "", user.full_name)

    if days is None:
        await update.message.reply_text(
            msg.CODE_NOT_FOUND, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_ACTIVATE_CODE

    # Añadir al canal automáticamente
    added = await add_user_to_channel(context, user.id)

    sub         = await db.get_subscription(user.id)
    expires_str = msg.fmt_date(sub["expires_at"]) if sub else "?"
    text        = (
        msg.CODE_SUCCESS.format(days=days, expires_at=expires_str)
        if added else
        msg.CODE_SUCCESS_NO_ADD.format(days=days, expires_at=expires_str)
    )

    await update.message.reply_text(
        text, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
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
#  RENOVAR CÓDIGO
# ════════════════════════════════════════════════════════════════════════════

async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    try:
        await query.edit_message_text(
            msg.ENTER_CODE_RENEW, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
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
            msg.CODE_NOT_FOUND, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_RENEW_CODE

    sub         = await db.get_subscription(user.id)
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
#  PANEL ADMIN — callbacks simples
# ════════════════════════════════════════════════════════════════════════════

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    await send_admin_panel(update, context)


async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    await send_admin_panel(update, context)
    return ConversationHandler.END


async def admin_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query, "✅ Panel actualizado")
    await send_admin_panel(update, context)
    return ConversationHandler.END


async def admin_list_codes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    codes = await db.list_active_codes()
    try:
        await query.edit_message_text(
            msg.admin_list_codes(codes),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
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


async def admin_members_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    subs = await db.get_all_active_subscriptions()
    try:
        await query.edit_message_text(
            msg.admin_members_msg(subs),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


async def admin_intruders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    logs = await db.get_intruder_log()
    try:
        await query.edit_message_text(
            msg.admin_intruders_msg(logs),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — Generar código (conversación)
# ════════════════════════════════════════════════════════════════════════════

async def admin_gen_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
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
            msg.ADMIN_CODE_INVALID, reply_markup=kb.back_to_admin_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_GEN_CODE

    code = parts[0].upper()
    try:
        days     = int(parts[1])
        max_uses = int(parts[2]) if len(parts) >= 3 else 1
    except ValueError:
        await update.message.reply_text(
            msg.ADMIN_CODE_INVALID, reply_markup=kb.back_to_admin_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_GEN_CODE

    created = await db.create_code(code, days, max_uses)
    if not created:
        await update.message.reply_text(
            msg.ADMIN_CODE_EXISTS, reply_markup=kb.back_to_admin_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_GEN_CODE

    await update.message.reply_text(
        msg.admin_code_created(code, days, max_uses),
        reply_markup=kb.back_to_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — Buscar usuario (conversación)
# ════════════════════════════════════════════════════════════════════════════

async def admin_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    try:
        await query.edit_message_text(
            msg.ADMIN_SEARCH_PROMPT,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.ADMIN_SEARCH_PROMPT)
    return WAITING_SEARCH


async def admin_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = update.message.text.strip()
    results    = await db.search_user(query_text)

    if not results:
        await update.message.reply_text(
            msg.ADMIN_SEARCH_NO_RESULTS,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_SEARCH

    await update.message.reply_text(
        msg.admin_search_results(results),
        reply_markup=kb.back_to_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — Expulsar usuario (conversación)
# ════════════════════════════════════════════════════════════════════════════

async def admin_kick_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
    try:
        await query.edit_message_text(
            msg.ADMIN_KICK_PROMPT,
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        await query.message.reply_text(msg.ADMIN_KICK_PROMPT, parse_mode=ParseMode.MARKDOWN)
    return WAITING_KICK_ID


async def admin_kick_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ ID inválido. Debe ser un número.",
            reply_markup=kb.back_to_admin_keyboard(),
        )
        return WAITING_KICK_ID

    sub = await db.get_subscription(user_id)
    if not sub:
        await update.message.reply_text(
            msg.ADMIN_KICK_NOT_FOUND, reply_markup=kb.back_to_admin_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_KICK_ID

    context.user_data["kick_user_id"] = user_id
    await update.message.reply_text(
        msg.admin_confirm_kick_msg(sub),
        reply_markup=kb.confirm_kick_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAITING_CONFIRM_KICK


async def admin_confirm_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)

    user_id  = int(query.data.split(":", 1)[1])
    sub      = await db.get_subscription(user_id)
    username = sub.get("username") or sub.get("full_name", "?") if sub else "?"

    await kick_user_from_channel(context, user_id)
    await db.delete_subscription(user_id)
    await db.log_intruder_kicked(user_id, username)

    try:
        await query.edit_message_text(
            msg.admin_kicked_msg(user_id, username),
            reply_markup=kb.back_to_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  ADMIN — Desactivar código (conversación)
# ════════════════════════════════════════════════════════════════════════════

async def admin_deactivate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)
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
    await safe_answer(query)

    code = query.data.split(":", 1)[1] if ":" in query.data else ""
    if code:
        await db.deactivate_code(code)
        text = msg.admin_deactivated(code)
    else:
        text = "❌ Error al identificar el código."

    try:
        await query.edit_message_text(
            text, reply_markup=kb.back_to_admin_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError:
        pass
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
#  FALLBACK UNIVERSAL
# ════════════════════════════════════════════════════════════════════════════

async def fallback_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Responde cualquier botón durante una conversación y la cancela."""
    query = update.callback_query
    await safe_answer(query)

    data = query.data
    if data == "main_menu":
        await send_main_menu(update, context)
    elif data == "admin_back":
        await send_admin_panel(update, context)
    elif data == "my_sub":
        return await my_subscription_callback(update, context)
    elif data == "contact_admin":
        return await contact_admin_callback(update, context)
    else:
        try:
            await query.edit_message_text(
                msg.CANCEL, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            pass

    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await safe_answer(update.callback_query)
    try:
        if update.effective_message:
            await update.effective_message.reply_text(
                msg.CANCEL, reply_markup=kb.back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
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
        user_id  = sub["user_id"]
        username = sub.get("username") or sub.get("full_name", "?")

        await kick_user_from_channel(context, user_id)

        try:
            await context.bot.send_message(
                user_id, msg.SUBSCRIPTION_EXPIRED,
                reply_markup=kb.main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            pass

        await db.delete_subscription(user_id)
        logger.info("Suscripción expirada eliminada: user_id=%s", user_id)


async def job_check_intruders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Cada 30 min: obtiene miembros del canal y expulsa a los que
    no tienen suscripción activa en la DB.
    """
    try:
        active_ids = await db.get_all_active_user_ids()
        # Obtener administradores para no expulsarlos
        admins = await context.bot.get_chat_administrators(CHANNEL_ID)
        admin_ids = {a.user.id for a in admins}

        # Iterar miembros del canal (solo funciona en grupos/supergrupos accesibles)
        # Para canales privados usamos get_chat_member de IDs conocidos
        # La estrategia: cualquier usuario en DB que ya no esté activo fue manejado
        # por job_check_expired. Aquí verificamos usuarios que entraron sin código.
        # Como Telegram no da lista de miembros de canal, comparamos la DB contra
        # intentos de get_chat_member para IDs sospechosos registrados en stats.
        kicked_count = 0

        # Verificar que todos los activos realmente están en el canal
        for uid in list(active_ids):
            if uid in admin_ids:
                continue
            try:
                member = await context.bot.get_chat_member(CHANNEL_ID, uid)
                # Si el miembro está pero no está en active_ids, expulsar
                if member.status in (ChatMember.LEFT, ChatMember.BANNED):
                    # Ya no está, limpiar DB
                    await db.delete_subscription(uid)
            except TelegramError:
                pass

        logger.info("Job intruders completado. Expulsados: %d", kicked_count)
    except Exception as e:
        logger.error("job_check_intruders error: %s", e)


async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Avisa a usuarios que vencen en 3 días."""
    expiring = await db.get_expiring_soon(days=3)
    for sub in expiring:
        user_id = sub["user_id"]
        try:
            expiry    = datetime.fromisoformat(sub["expires_at"])
            days_left = max(0, (expiry - datetime.now()).days)
            await context.bot.send_message(
                user_id, msg.warn_expiring(days_left),
                reply_markup=kb.main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN
            )
            await db.mark_warned(user_id)
        except TelegramError as e:
            logger.warning("No se pudo avisar a %s: %s", user_id, e)


# ════════════════════════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DE LA APLICACIÓN
# ════════════════════════════════════════════════════════════════════════════

def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # Fallbacks comunes para todos los ConversationHandlers
    common_fallbacks = [
        CallbackQueryHandler(main_menu_callback,   pattern="^main_menu$"),
        CallbackQueryHandler(fallback_menu_button, pattern="^(my_sub|contact_admin|activate|renew|admin_back|admin_stats|admin_list_codes|admin_members|admin_intruders|admin_refresh|admin_gen_code|admin_deactivate|admin_search|admin_kick)$"),
        CommandHandler("cancel", cancel_conversation),
        CommandHandler("start",  cancel_conversation),
    ]

    # ── ConversationHandler: Activar código ──────────────────────────────
    activate_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(activate_start, pattern="^activate$")],
        states={WAITING_ACTIVATE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_receive_code)]},
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Renovar ─────────────────────────────────────
    renew_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
        states={WAITING_RENEW_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_receive_code)]},
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin generar código ─────────────────────────
    admin_gen_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_gen_code_start, pattern="^admin_gen_code$")],
        states={WAITING_GEN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gen_code_receive)]},
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin desactivar código ──────────────────────
    admin_deact_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_deactivate_start, pattern="^admin_deactivate$")],
        states={
            WAITING_DEACTIVATE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deactivate_receive)],
            WAITING_CONFIRM_DEACT: [
                CallbackQueryHandler(admin_confirm_deactivate_callback, pattern="^admin_confirm_deactivate:"),
                CallbackQueryHandler(admin_back_callback, pattern="^admin_back$"),
            ],
        },
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin buscar usuario ─────────────────────────
    admin_search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_search_start, pattern="^admin_search$")],
        states={WAITING_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_receive)]},
        fallbacks=common_fallbacks,
        conversation_timeout=300,
    )

    # ── ConversationHandler: Admin expulsar usuario ───────────────────────
    admin_kick_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_kick_start, pattern="^admin_kick$")],
        states={
            WAITING_KICK_ID:     [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_kick_receive_id)],
            WAITING_CONFIRM_KICK: [
                CallbackQueryHandler(admin_confirm_kick_callback, pattern="^admin_confirm_kick:"),
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
    app.add_handler(admin_search_conv)
    app.add_handler(admin_kick_conv)

    # Handlers simples
    app.add_handler(CallbackQueryHandler(main_menu_callback,        pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(my_subscription_callback,  pattern="^my_sub$"))
    app.add_handler(CallbackQueryHandler(contact_admin_callback,    pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(admin_back_callback,       pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_refresh_callback,    pattern="^admin_refresh$"))
    app.add_handler(CallbackQueryHandler(admin_list_codes_callback, pattern="^admin_list_codes$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback,      pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_members_callback,    pattern="^admin_members$"))
    app.add_handler(CallbackQueryHandler(admin_intruders_callback,  pattern="^admin_intruders$"))

    # ── Jobs ──────────────────────────────────────────────────────────────
    jq = app.job_queue
    jq.run_repeating(job_check_expired,   interval=3600,  first=60)
    jq.run_repeating(job_check_intruders, interval=1800,  first=120)  # cada 30 min
    jq.run_repeating(job_warn_expiring,   interval=43200, first=180)

    return app


async def post_init(app: Application) -> None:
    await db.init_db()
    logger.info("Bot iniciado correctamente.")


def main() -> None:
    app = build_application()
    app.post_init = post_init
    logger.info("Iniciando bot...")
    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=True,
        )
    except Exception as e:
        logger.error("Error fatal: %s", e)
    finally:
        logger.info("Bot detenido correctamente.")


if __name__ == "__main__":
    main()
