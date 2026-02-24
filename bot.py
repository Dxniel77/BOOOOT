"""
bot.py — Bot de suscripción v3: 100% botones, flujo guiado
python-telegram-bot==20.7 | Python 3.11 | Railway
"""

import logging
import os
from datetime import datetime

from telegram import Update, BotCommand
from telegram.constants import ParseMode
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

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Estados del ConversationHandler ──────────────────────────────────────────
# Usuario
S_WAITING_ACTIVATE_CODE = 10
S_WAITING_RENEW_CODE    = 11

# Admin
S_ADMIN_WAITING_GEN    = 20
S_ADMIN_WAITING_DEACT  = 21


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


async def safe_kick(context, user_id: int) -> bool:
    try:
        await context.bot.ban_chat_member(CHANNEL_ID, user_id)
        await context.bot.unban_chat_member(CHANNEL_ID, user_id)
        return True
    except Exception as e:
        logger.warning("Kick failed for %s: %s", user_id, e)
        return False


async def safe_send(context, chat_id: int, text: str, **kwargs) -> None:
    try:
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception as e:
        logger.warning("send_message failed to %s: %s", chat_id, e)


async def show_user_menu(update: Update, user_id: int, edit: bool = False) -> None:
    """Muestra el menú principal del usuario (nuevo mensaje o edita el actual)."""
    sub = db.get_active_subscription(user_id)
    has_sub = sub is not None
    text = msg.menu_user_active(sub["expires_at"]) if has_sub else msg.menu_user_no_sub()
    markup = kb.user_main_menu(has_sub)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
        )
    else:
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)


# ═══════════════════════════════════════════════════════════════════════════════
#  FLUJO USUARIO — ConversationHandler
# ═══════════════════════════════════════════════════════════════════════════════

async def user_entry_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point: /start — muestra bienvenida + menú."""
    user = update.effective_user
    await update.message.reply_text(
        msg.welcome(user.first_name),
        parse_mode=ParseMode.MARKDOWN,
    )
    await show_user_menu(update, user.id)


# ── Activar ───────────────────────────────────────────────────────────────────

async def user_activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botón 🔑 Activar código → pide el código."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    existing = db.get_active_subscription(user_id)
    if existing:
        await query.edit_message_text(
            msg.err_already_active(existing["expires_at"]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_main_menu(has_sub=True),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        msg.ask_for_code("activate"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.user_cancel(),
    )
    return S_WAITING_ACTIVATE_CODE


async def user_activate_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe el código del usuario y procesa la activación."""
    user  = update.effective_user
    code  = update.message.text.strip().upper()

    # Borrar el mensaje del código (privacidad)
    try:
        await update.message.delete()
    except Exception:
        pass

    code_row = db.get_code(code)
    if not code_row:
        await update.message.reply_text(
            msg.err_code_invalid(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_cancel(),
        )
        return S_WAITING_ACTIVATE_CODE  # dejar que reintente

    if code_row["used_times"] >= code_row["max_uses"]:
        await update.message.reply_text(
            msg.err_code_exhausted(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_main_menu(has_sub=False),
        )
        return ConversationHandler.END

    expires_at = db.create_subscription(
        user_id    = user.id,
        username   = user.username or "",
        first_name = user.first_name or "",
        code       = code,
        days       = code_row["days"],
    )
    db.use_code(code)

    # Crear invite link
    invite_url = None
    try:
        link = await context.bot.create_chat_invite_link(
            CHANNEL_ID,
            member_limit=1,
            expire_date=datetime.fromisoformat(expires_at),
        )
        invite_url = link.invite_link
    except Exception as e:
        logger.error("Invite link error: %s", e)

    reply = msg.activated_ok(user.first_name, expires_at)
    if invite_url:
        reply += f"\n\n🔗 [Unirte al canal]({invite_url})"

    await update.message.reply_text(
        reply,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.user_after_success(),
    )

    await safe_send(
        context, ADMIN_ID,
        msg.admin_new_activation(user.first_name, user.id, code, expires_at),
    )
    return ConversationHandler.END


# ── Renovar ───────────────────────────────────────────────────────────────────

async def user_renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botón 🔄 Renovar → verifica suscripción y pide código."""
    query = update.callback_query
    await query.answer()

    if not db.get_active_subscription(update.effective_user.id):
        await query.edit_message_text(
            msg.err_no_sub_to_renew(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_main_menu(has_sub=False),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        msg.ask_for_code("renew"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.user_cancel(),
    )
    return S_WAITING_RENEW_CODE


async def user_renew_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe el código de renovación."""
    user = update.effective_user
    code = update.message.text.strip().upper()

    try:
        await update.message.delete()
    except Exception:
        pass

    existing = db.get_active_subscription(user.id)
    if not existing:
        await update.message.reply_text(
            msg.err_no_sub_to_renew(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_main_menu(has_sub=False),
        )
        return ConversationHandler.END

    code_row = db.get_code(code)
    if not code_row:
        await update.message.reply_text(
            msg.err_code_invalid(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_cancel(),
        )
        return S_WAITING_RENEW_CODE  # reintento

    if code_row["used_times"] >= code_row["max_uses"]:
        await update.message.reply_text(
            msg.err_code_exhausted(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.user_main_menu(has_sub=True),
        )
        return ConversationHandler.END

    new_expires = db.renew_subscription(existing["id"], code_row["days"])
    db.use_code(code)

    await update.message.reply_text(
        msg.renewed_ok(new_expires),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.user_after_success(),
    )

    await safe_send(
        context, ADMIN_ID,
        msg.admin_renewal(user.first_name, user.id, code, new_expires),
    )
    return ConversationHandler.END


# ── Cancelar (botón) ──────────────────────────────────────────────────────────

async def user_cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await show_user_menu(update, update.effective_user.id, edit=True)
    return ConversationHandler.END


# ── Callbacks de menú de usuario ──────────────────────────────────────────────

async def user_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callbacks que no inician conversación: status, menu, contact."""
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    data = query.data

    if data == "u:menu":
        await show_user_menu(update, uid, edit=True)

    elif data == "u:status":
        sub = db.get_active_subscription(uid)
        if not sub:
            await query.edit_message_text(
                msg.status_no_sub(),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.user_main_menu(has_sub=False),
            )
        else:
            await query.edit_message_text(
                msg.menu_user_active(sub["expires_at"]),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.user_status_buttons(),
            )




# ═══════════════════════════════════════════════════════════════════════════════
#  FLUJO ADMIN — ConversationHandler
# ═══════════════════════════════════════════════════════════════════════════════

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Abre el panel admin via /admin."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.admin_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        msg.admin_menu(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_main_menu(),
    )


# ── Generar código ────────────────────────────────────────────────────────────

async def admin_gen_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        msg.admin_ask_code_data(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_cancel(),
    )
    return S_ADMIN_WAITING_GEN


async def admin_gen_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text.lower() == "cancelar":
        await update.message.reply_text(
            msg.admin_menu(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_main_menu(),
        )
        return ConversationHandler.END

    parts = text.split()
    if len(parts) < 3:
        await update.message.reply_text(
            "❌ Formato: `CODIGO DIAS USOS`\n_Ejemplo:_ `VIP30 30 5`\n\nEscribe `cancelar` para salir.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return S_ADMIN_WAITING_GEN

    code = parts[0].upper()
    try:
        days, max_uses = int(parts[1]), int(parts[2])
    except ValueError:
        await update.message.reply_text(
            "❌ Días y usos deben ser números.\n\nInténtalo de nuevo.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return S_ADMIN_WAITING_GEN

    if days <= 0 or max_uses <= 0:
        await update.message.reply_text("❌ Los valores deben ser > 0.")
        return S_ADMIN_WAITING_GEN

    if not db.create_code(code, days, max_uses, update.effective_user.id):
        await update.message.reply_text(
            msg.admin_code_exists(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return S_ADMIN_WAITING_GEN

    await update.message.reply_text(
        msg.admin_code_created(code, days, max_uses),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_back(),
    )
    return ConversationHandler.END


# ── Desactivar código ─────────────────────────────────────────────────────────

async def admin_deact_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        msg.admin_ask_deactivate(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_cancel(),
    )
    return S_ADMIN_WAITING_DEACT


async def admin_deact_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text.lower() == "cancelar":
        await update.message.reply_text(
            msg.admin_menu(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_main_menu(),
        )
        return ConversationHandler.END

    code = text.upper()
    if not db.get_code(code):
        await update.message.reply_text(
            msg.admin_code_not_found(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return S_ADMIN_WAITING_DEACT

    await update.message.reply_text(
        f"¿Confirmas desactivar el código `{code}`?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_confirm_deactivate(code),
    )
    return ConversationHandler.END


# ── Callbacks admin (sin conversación) ───────────────────────────────────────

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid  = update.effective_user.id
    data = query.data

    if not is_admin(uid):
        await query.edit_message_text("🚫 Sin permisos.")
        return

    if data in ("a:menu", "a:refresh"):
        await query.edit_message_text(
            msg.admin_menu(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_main_menu(),
        )

    elif data == "a:stats":
        await query.edit_message_text(
            msg.admin_stats(db.get_stats()),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_back(),
        )

    elif data == "a:list":
        codes = db.list_codes(only_active=True)
        await query.edit_message_text(
            msg.admin_codes_list(codes),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_back(),
        )

    elif data == "a:users":
        s = db.get_stats()
        await query.edit_message_text(
            f"👥 *Usuarios activos:* `{s['active_users']}`\n"
            f"⚠️ *Vencen en ≤3d:*   `{s['expiring_soon']}`\n"
            f"📈 *Activaciones hoy:* `{s['uses_today']}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_back(),
        )

    elif data.startswith("a:deact_ok:"):
        code = data.split(":", 2)[2]
        db.deactivate_code(code)
        await query.edit_message_text(
            msg.admin_deactivated(code),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_back(),
        )


# ── Comando rápido /generar (también funciona desde chat) ─────────────────────

async def cmd_generar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.admin_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "⚠️ Uso: `/generar CODIGO DIAS USOS`\n_Ej:_ `/generar VIP30 30 5`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    code = args[0].upper()
    try:
        days, max_uses = int(args[1]), int(args[2])
    except ValueError:
        await update.message.reply_text("❌ Días y usos deben ser números.", parse_mode=ParseMode.MARKDOWN)
        return
    if not db.create_code(code, days, max_uses, update.effective_user.id):
        await update.message.reply_text(msg.admin_code_exists(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        msg.admin_code_created(code, days, max_uses),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_back(),
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.admin_not_authorized(), parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        msg.admin_stats(db.get_stats()),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_back(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  JOB PERIÓDICO
# ═══════════════════════════════════════════════════════════════════════════════

async def job_check_expirations(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Expulsar vencidos
    for sub in db.get_expired_active():
        uid, name = sub["user_id"], sub["first_name"] or "Usuario"
        kicked = await safe_kick(context, uid)
        db.mark_expired(sub["id"])
        db.deactivate_subscription(uid)

        # Notificar al usuario con botón para reactivar
        try:
            await context.bot.send_message(
                uid,
                msg.expired_notice(name),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.user_main_menu(has_sub=False),
            )
        except Exception:
            pass

        await safe_send(
            context, ADMIN_ID,
            msg.admin_user_kicked(uid, name) if kicked else msg.admin_kick_failed(uid),
        )

    # Avisar próximos a vencer
    for sub in db.get_expiring_soon(days=3):
        try:
            await context.bot.send_message(
                sub["user_id"],
                msg.expiry_warning(sub["first_name"] or "Usuario", sub["expires_at"]),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.user_main_menu(has_sub=True),
            )
        except Exception:
            pass
        db.mark_notified(sub["id"])

    logger.info("✅ job_check_expirations completado.")


# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",    "Abrir menú principal"),
        BotCommand("admin",    "[ADMIN] Panel de administración"),
        BotCommand("generar",  "[ADMIN] Crear código rápido"),
        BotCommand("stats",    "[ADMIN] Ver estadísticas"),
    ])


def main() -> None:
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── ConversationHandler USUARIO ──────────────────────────────────────────
    user_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(user_activate_start, pattern="^u:activate_start$"),
            CallbackQueryHandler(user_renew_start,    pattern="^u:renew_start$"),
        ],
        states={
            S_WAITING_ACTIVATE_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_activate_receive),
                CallbackQueryHandler(user_cancel_flow, pattern="^u:cancel$"),
            ],
            S_WAITING_RENEW_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_renew_receive),
                CallbackQueryHandler(user_cancel_flow, pattern="^u:cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(user_cancel_flow, pattern="^u:cancel$"),
            CommandHandler("start", user_entry_start),
        ],
        per_user=True,
        per_chat=True,
    )

    # ── ConversationHandler ADMIN ────────────────────────────────────────────
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_gen_start,   pattern="^a:gen_start$"),
            CallbackQueryHandler(admin_deact_start, pattern="^a:deact_start$"),
        ],
        states={
            S_ADMIN_WAITING_GEN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID),
                    admin_gen_receive,
                ),
            ],
            S_ADMIN_WAITING_DEACT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID),
                    admin_deact_receive,
                ),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(lambda u, c: (u.callback_query.answer(), None)[1], pattern="^a:menu$"),
            CommandHandler("admin", admin_entry),
        ],
        per_user=True,
        per_chat=True,
    )

    # ── Registrar handlers ───────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",   user_entry_start))
    app.add_handler(CommandHandler("admin",   admin_entry))
    app.add_handler(CommandHandler("generar", cmd_generar))
    app.add_handler(CommandHandler("stats",   cmd_stats))

    app.add_handler(user_conv)
    app.add_handler(admin_conv)

    # Callbacks simples (no inician conversación)
    app.add_handler(CallbackQueryHandler(user_callbacks,  pattern="^u:"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^a:"))

    # Job periódico: cada hora
    app.job_queue.run_repeating(
        job_check_expirations,
        interval=3600,
        first=30,
        name="expirations",
    )

    logger.info("🤖 Bot v3 iniciado — 100%% botones")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
