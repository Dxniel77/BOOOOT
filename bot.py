"""
╔══════════════════════════════════════════════════════╗
║               DX VIP BOT — bot.py                    ║
║  Bot de suscripción a canal privado de Telegram      ║
║  python-telegram-bot 21.6 | aiosqlite | Python 3.11  ║
╚══════════════════════════════════════════════════════╝
"""

import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

from telegram import Bot, ChatMember, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
import keyboards as kb
import messages as msg

# ══════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN:  str = os.environ["BOT_TOKEN"]
ADMIN_ID:   int = int(os.environ["ADMIN_ID"])
CHANNEL_ID: int = int(os.environ["CHANNEL_ID"])

FREE_TRIAL_DAYS = 2
REFERRAL_BONUS_DAYS = 7

# Estados de conversación
(
    ST_ACTIVATE,
    ST_RENEW,
    ST_ADMIN_GEN,
    ST_ADMIN_SEARCH,
    ST_ADMIN_KICK,
    ST_ADMIN_BAN,
    ST_ADMIN_UNBAN,
    ST_ADMIN_BROADCAST,
    ST_ADMIN_BROADCAST_CONFIRM,
) = range(9)


# ══════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except TelegramError as exc:
        logger.error("safe_send → %s: %s", chat_id, exc)
        return False


async def generate_unique_code() -> str:
    charset = string.ascii_uppercase + string.digits
    for _ in range(30):
        suffix = "".join(secrets.choice(charset) for _ in range(6))
        code   = f"VIP-{suffix}"
        if not await db.code_exists(code):
            return code
    return f"VIP-{secrets.token_hex(4).upper()}"


async def kick_user(bot: Bot, user_id: int) -> bool:
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return True
    except TelegramError as exc:
        logger.error("kick_user %s: %s", user_id, exc)
        return False


async def create_invite(bot: Bot) -> str | None:
    try:
        link = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return link.invite_link
    except TelegramError as exc:
        logger.error("create_invite: %s", exc)
        return None


# ══════════════════════════════════════════════
# /start — BIENVENIDA + REFERIDOS
# ══════════════════════════════════════════════

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # Verificar blacklist
    if await db.is_blacklisted(user.id):
        await update.message.reply_text(msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return

    # Procesar link de referido: /start ref_USER_ID
    referred_by = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                ref_id = int(arg[4:])
                if ref_id != user.id:
                    referred_by = ref_id
                    # Guardar en context para usar al activar
                    context.user_data["referred_by"] = ref_id
                    # Obtener nombre del referidor
                    ref_sub = await db.get_subscription(ref_id)
                    ref_name = ref_sub["full_name"] if ref_sub else "tu amigo/a"
                    await update.message.reply_text(
                        msg.referral_welcome(ref_name),
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except (ValueError, TypeError):
                pass

    await db.log_event("start", user.id, user.username)
    await update.message.reply_text(
        msg.welcome(user.first_name),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if await db.is_blacklisted(user.id):
        await query.edit_message_text(msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return
    await query.edit_message_text(
        msg.welcome(user.first_name),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        msg.HELP_TEXT,
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def auto_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde a mensajes de texto libre que no son comandos ni están en conversación."""
    user = update.effective_user
    if await db.is_blacklisted(user.id):
        await update.message.reply_text(msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        msg.AUTO_RESPONSE,
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# PRUEBA GRATIS
# ══════════════════════════════════════════════

async def free_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if await db.is_blacklisted(user.id):
        await query.edit_message_text(msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return
    if await db.has_used_free_trial(user.id):
        await query.edit_message_text(
            msg.FREE_TRIAL_ALREADY_USED,
            reply_markup=kb.back_to_main(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await query.edit_message_text(
        msg.FREE_TRIAL_PROMPT,
        reply_markup=kb.confirm_free_trial(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def confirm_free_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("⏳ Activando prueba...")
    user = update.effective_user

    if await db.has_used_free_trial(user.id):
        await query.edit_message_text(
            msg.FREE_TRIAL_ALREADY_USED,
            reply_markup=kb.back_to_main(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    invite = await create_invite(context.bot)
    if not invite:
        await query.edit_message_text(msg.GENERIC_ERROR, reply_markup=kb.back_to_main(),
                                       parse_mode=ParseMode.MARKDOWN)
        return

    expires_at = datetime.now(timezone.utc) + timedelta(days=FREE_TRIAL_DAYS)
    referred_by = context.user_data.get("referred_by")

    await db.upsert_subscription(
        user_id=user.id, username=user.username, full_name=user.full_name,
        expires_at=expires_at, code_used="FREE-TRIAL", invite_link=invite,
        days=FREE_TRIAL_DAYS, referred_by=referred_by,
    )
    await db.mark_free_trial_used(user.id)
    await db.log_event("free_trial", user.id)
    await db.audit(ADMIN_ID, "free_trial_activated", user.id, user.username)

    await query.edit_message_text(
        msg.free_trial_activated(expires_at, invite),
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# MEMBRESÍA
# ══════════════════════════════════════════════

async def my_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    sub  = await db.get_subscription(user.id)

    if sub is None:
        await query.edit_message_text(
            msg.NO_SUBSCRIPTION, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
        )
        return

    exp = datetime.fromisoformat(sub["expires_at"])
    cre = datetime.fromisoformat(sub["created_at"])
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if cre.tzinfo is None:
        cre = cre.replace(tzinfo=timezone.utc)

    ref_count = await db.get_referral_count(user.id)

    await query.edit_message_text(
        msg.membership_card(
            full_name=sub["full_name"] or user.full_name,
            username=sub["username"],
            expires_at=exp,
            created_at=cre,
            code_used=sub["code_used"],
            renewals=sub["renewals"],
            total_days=sub["total_days"],
            referral_count=ref_count,
        ),
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# REFERIDOS
# ══════════════════════════════════════════════

async def get_referral_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    bot_me = await context.bot.get_me()
    await query.edit_message_text(
        msg.referral_link_message(update.effective_user.id, bot_me.username),
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def my_referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user      = update.effective_user
    count     = await db.get_referral_count(user.id)
    refs      = await db.get_referrals_by_referrer(user.id)
    bonus_total = sum(r["bonus_days"] for r in refs if r["bonus_given"])
    await query.edit_message_text(
        msg.my_referrals_message(count, bonus_total),
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# HISTORIAL
# ══════════════════════════════════════════════

async def my_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user   = update.effective_user
    events = await db.get_user_events(user.id, limit=20)
    await query.edit_message_text(
        msg.user_history(events),
        reply_markup=kb.back_to_main(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# CONV: Activar código
# ══════════════════════════════════════════════

async def activate_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if await db.is_blacklisted(user.id):
        await query.edit_message_text(msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    # Si ya tiene suscripción activa
    sub = await db.get_subscription(user.id)
    if sub:
        exp = datetime.fromisoformat(sub["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > datetime.now(timezone.utc):
            await query.edit_message_text(
                msg.CODE_ALREADY_SUBSCRIBED,
                reply_markup=kb.main_menu(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

    await query.edit_message_text(
        msg.ASK_CODE, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ACTIVATE


async def activate_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user  = update.effective_user
    code  = update.message.text.strip().upper()

    code_row = await db.get_code(code)
    if code_row is None:
        await update.message.reply_text(
            msg.CODE_NOT_FOUND, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
        )
        return ST_ACTIVATE

    if not code_row["is_active"]:
        await update.message.reply_text(
            msg.CODE_INACTIVE, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    invite = await create_invite(context.bot)
    if not invite:
        await update.message.reply_text(
            msg.GENERIC_ERROR, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    days       = code_row["days"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    referred_by = context.user_data.get("referred_by")

    await db.upsert_subscription(
        user_id=user.id, username=user.username, full_name=user.full_name,
        expires_at=expires_at, code_used=code, invite_link=invite,
        days=days, referred_by=referred_by,
    )
    await db.increment_code_usage(code)
    await db.log_event("code_activated", user.id, code)

    # Procesar referido
    if referred_by:
        created = await db.create_referral(referred_by, user.id, REFERRAL_BONUS_DAYS)
        if created:
            # Dar bonus al referidor
            new_exp = await db.add_days_to_subscription(referred_by, REFERRAL_BONUS_DAYS)
            if new_exp:
                await safe_send(
                    context.bot, referred_by,
                    msg.REFERRAL_BONUS_GRANTED,
                    parse_mode=ParseMode.MARKDOWN,
                )
                await db.log_event("referral_bonus", referred_by, str(user.id))
        context.user_data.pop("referred_by", None)

    await update.message.reply_text(
        msg.code_activated(expires_at, invite, days),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# CONV: Renovar código
# ══════════════════════════════════════════════

async def renew_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not await db.get_subscription(user.id):
        await query.edit_message_text(
            msg.NO_SUBSCRIPTION_TO_RENEW,
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ASK_RENEW_CODE, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_RENEW


async def renew_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    code = update.message.text.strip().upper()

    code_row = await db.get_code(code)
    if code_row is None:
        await update.message.reply_text(
            msg.CODE_NOT_FOUND, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
        )
        return ST_RENEW

    if not code_row["is_active"]:
        await update.message.reply_text(
            msg.CODE_INACTIVE, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    days    = code_row["days"]
    new_exp = await db.add_days_to_subscription(user.id, days)
    if new_exp is None:
        await update.message.reply_text(
            msg.NO_SUBSCRIPTION_TO_RENEW, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await db.increment_code_usage(code)
    await db.log_event("code_renewed", user.id, code)

    await update.message.reply_text(
        msg.code_renewed(new_exp, days),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# ADMIN — /admin
# ══════════════════════════════════════════════

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.NOT_ADMIN)
        return
    counts = await db.count_subscriptions()
    await update.message.reply_text(
        msg.admin_panel_text(counts),
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    counts = await db.count_subscriptions()
    await query.edit_message_text(
        msg.admin_panel_text(counts),
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("✅ Actualizado")
    if not is_admin(update.effective_user.id):
        return
    counts = await db.count_subscriptions()
    await query.edit_message_text(
        msg.admin_panel_text(counts),
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════
# CONV ADMIN: Generar código
# ══════════════════════════════════════════════

async def admin_gen_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_GEN_CODE_PROMPT,
        reply_markup=kb.admin_gen_code_shortcuts(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ST_ADMIN_GEN


async def admin_gen_code_quick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    parts = query.data.split("_")  # admin_quickcode_30_5
    try:
        days = int(parts[-2])
        uses = int(parts[-1])
    except (ValueError, IndexError):
        return ST_ADMIN_GEN

    code    = await generate_unique_code()
    created = await db.create_code(code, days, uses, created_by=ADMIN_ID)
    if created:
        await db.audit(ADMIN_ID, "code_created", detail=f"{code}:{days}d:{uses}u")
        await query.edit_message_text(
            msg.admin_code_created(code, days, uses, auto=True),
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.edit_message_text(
            "❌ Error de colisión. Intenta de nuevo.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


async def admin_gen_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text  = update.message.text.strip()
    parts = text.split()
    auto  = False
    note  = None

    try:
        if len(parts) == 2:
            days, uses = int(parts[0]), int(parts[1])
            if days <= 0 or uses <= 0:
                raise ValueError
            code = await generate_unique_code()
            auto = True
        elif len(parts) >= 3:
            code = parts[0].upper()
            days = int(parts[1])
            uses = int(parts[2])
            if days <= 0 or uses <= 0:
                raise ValueError
            if len(parts) >= 4:
                note = parts[3]
        else:
            await update.message.reply_text(
                msg.ADMIN_GEN_CODE_FORMAT_ERROR,
                reply_markup=kb.admin_gen_code_shortcuts(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return ST_ADMIN_GEN
    except ValueError:
        await update.message.reply_text(
            msg.ADMIN_GEN_CODE_VALUE_ERROR,
            reply_markup=kb.admin_gen_code_shortcuts(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ST_ADMIN_GEN

    created = await db.create_code(code, days, uses, note=note, created_by=ADMIN_ID)
    if not created:
        await update.message.reply_text(
            f"❌ El código `{code}` ya existe.",
            reply_markup=kb.admin_gen_code_shortcuts(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ST_ADMIN_GEN

    await db.audit(ADMIN_ID, "code_created", detail=f"{code}:{days}d:{uses}u")
    await update.message.reply_text(
        msg.admin_code_created(code, days, uses, auto=auto, note=note),
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# ADMIN — Listar, stats, miembros
# ══════════════════════════════════════════════

async def admin_list_codes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = await db.list_codes()
    text = msg.admin_codes_list(rows)
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...truncado_"
    await query.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    summary      = await db.get_stats_summary()
    recent       = await db.get_recent_events(10)
    daily_events = await db.get_stats_last_days(7)
    daily_users  = await db.get_new_users_last_days(7)
    text = msg.admin_stats_text(summary, recent, daily_events, daily_users)
    if len(text) > 4000:
        text = text[:4000] + "\n_...truncado_"
    await query.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


async def admin_members_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = await db.get_active_subscriptions()
    text = msg.admin_members_text(rows)
    if len(text) > 4000:
        text = text[:4000] + "\n_...truncado_"
    await query.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════
# CONV ADMIN: Buscar usuario
# ══════════════════════════════════════════════

async def admin_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_SEARCH_PROMPT, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ADMIN_SEARCH


async def admin_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rows = await db.search_user(update.message.text.strip())
    if not rows:
        await update.message.reply_text(
            msg.ADMIN_SEARCH_NO_RESULTS, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    text = msg.admin_search_results(rows)
    if len(text) > 4000:
        text = text[:4000] + "\n_...truncado_"
    await update.message.reply_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ══════════════════════════════════════════════
# CONV ADMIN: Expulsar usuario
# ══════════════════════════════════════════════

async def admin_kick_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_KICK_PROMPT, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ADMIN_KICK


async def admin_kick_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ Introduce un ID numérico.", reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
        )
        return ST_ADMIN_KICK
    user_id = int(text)
    row = await db.get_subscription(user_id)
    if row is None:
        await update.message.reply_text(
            msg.ADMIN_KICK_NOT_FOUND, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    context.user_data["kick_uid"] = user_id
    await update.message.reply_text(
        msg.admin_kick_confirm_text(row),
        reply_markup=kb.admin_confirm_kick(user_id),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def admin_kick_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    user_id = int(query.data.replace("admin_kick_confirm_", ""))
    kicked  = await kick_user(context.bot, user_id)
    await db.delete_subscription(user_id)
    await db.log_event("admin_kicked", user_id)
    await db.audit(ADMIN_ID, "kick", user_id)
    await safe_send(context.bot, user_id, msg.subscription_expired_msg(), parse_mode=ParseMode.MARKDOWN)
    if kicked:
        await query.edit_message_text(
            msg.admin_kicked_ok(user_id), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
            msg.ADMIN_KICK_ERROR + f"\n_DB limpiada para `{user_id}`_",
            reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN,
        )


# ══════════════════════════════════════════════
# CONV ADMIN: Banear usuario
# ══════════════════════════════════════════════

async def admin_ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_BAN_PROMPT, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ADMIN_BAN


async def admin_ban_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split(None, 1)
    if not parts or not parts[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ Formato: `USER_ID RAZÓN`", reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
        )
        return ST_ADMIN_BAN

    user_id = int(parts[0])
    reason  = parts[1] if len(parts) > 1 else None
    sub     = await db.get_subscription(user_id)
    uname   = sub["username"]   if sub else None
    fname   = sub["full_name"]  if sub else None

    await db.add_to_blacklist(user_id, uname, fname, reason, banned_by=ADMIN_ID)
    # Si tiene suscripción activa, expulsarle también
    if sub:
        await kick_user(context.bot, user_id)
        await db.delete_subscription(user_id)
    await db.audit(ADMIN_ID, "ban", user_id, reason)
    await safe_send(context.bot, user_id, msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(
        msg.admin_banned_ok(user_id), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# CONV ADMIN: Desbanear usuario
# ══════════════════════════════════════════════

async def admin_unban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_UNBAN_PROMPT, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ADMIN_UNBAN


async def admin_unban_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ Introduce un ID numérico.", reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
        )
        return ST_ADMIN_UNBAN
    user_id = int(text)
    removed = await db.remove_from_blacklist(user_id)
    if removed:
        await db.audit(ADMIN_ID, "unban", user_id)
        await update.message.reply_text(
            msg.admin_unbanned_ok(user_id), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            msg.ADMIN_UNBAN_NOT_FOUND, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
        )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# ADMIN — Blacklist, Auditoría
# ══════════════════════════════════════════════

async def admin_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await query.edit_message_text(
        "🔇 *Gestión de Blacklist*\n`─────────────────────────`\n_Selecciona una acción:_",
        reply_markup=kb.admin_blacklist_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_view_blacklist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = await db.get_blacklist()
    text = msg.admin_blacklist_text(rows)
    if len(text) > 4000:
        text = text[:4000] + "\n_...truncado_"
    await query.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


async def admin_audit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = await db.get_audit_log(30)
    text = msg.admin_audit_text(rows)
    if len(text) > 4000:
        text = text[:4000] + "\n_...truncado_"
    await query.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════
# CONV ADMIN: Broadcast
# ══════════════════════════════════════════════

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        msg.ADMIN_BROADCAST_PROMPT, reply_markup=kb.cancel_button(), parse_mode=ParseMode.MARKDOWN
    )
    return ST_ADMIN_BROADCAST


async def admin_broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text   = update.message.text.strip()
    active = await db.get_active_subscriptions()
    context.user_data["broadcast_text"] = text
    await update.message.reply_text(
        msg.admin_broadcast_preview(text, len(active)),
        reply_markup=kb.admin_broadcast_confirm(text),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ST_ADMIN_BROADCAST_CONFIRM


async def admin_broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("📢 Enviando...")
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    text   = context.user_data.pop("broadcast_text", "")
    active = await db.get_active_subscriptions()
    sent   = 0
    failed = 0

    for sub in active:
        ok = await safe_send(
            context.bot, sub["user_id"], text, parse_mode=ParseMode.MARKDOWN
        )
        if ok:
            sent += 1
        else:
            failed += 1

    await db.log_broadcast(ADMIN_ID, text, sent, failed)
    await db.audit(ADMIN_ID, "broadcast", detail=f"sent:{sent} failed:{failed}")

    await query.edit_message_text(
        msg.admin_broadcast_done(sent, failed),
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# ADMIN — Intrusos, Mantenimiento, Backup
# ══════════════════════════════════════════════

async def admin_intruders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🔎 Escaneando...")
    if not is_admin(update.effective_user.id):
        return
    kicked = await _scan_intruders(context.bot)
    await query.edit_message_text(
        f"🕵️ *Escaneo completado*\n`─────────────────────────`\n"
        f"Intrusos/fantasmas limpiados: *{kicked}*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_maintenance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await query.edit_message_text(
        "⚙️ *Mantenimiento*\n`─────────────────────────`\n_Selecciona:_",
        reply_markup=kb.admin_maintenance_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_force_cleanup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🧹 Limpiando...")
    if not is_admin(update.effective_user.id):
        return
    kicked = await _cleanup_expired(context.bot)
    await query.edit_message_text(
        f"🧹 *Limpieza completada*\n`─────────────────────────`\n"
        f"Usuarios vencidos expulsados: *{kicked}*",
        reply_markup=kb.admin_maintenance_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_force_scan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("🔎 Escaneando...")
    if not is_admin(update.effective_user.id):
        return
    kicked = await _scan_intruders(context.bot)
    await query.edit_message_text(
        f"🔎 *Escaneo completado*\n`─────────────────────────`\n"
        f"Intrusos limpiados: *{kicked}*",
        reply_markup=kb.admin_maintenance_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_backup_db_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("💾 Enviando backup...")
    if not is_admin(update.effective_user.id):
        return
    import os
    from database import DB_PATH
    if not os.path.exists(DB_PATH):
        await query.answer("❌ DB no encontrada", show_alert=True)
        return
    try:
        with open(DB_PATH, "rb") as f:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=f,
                filename="dxvipbot_backup.db",
                caption=f"💾 *Backup de DB*\n`{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        await db.audit(ADMIN_ID, "db_backup")
        await query.answer("✅ Backup enviado", show_alert=True)
    except TelegramError as exc:
        logger.error("backup_db: %s", exc)
        await query.answer("❌ Error al enviar backup", show_alert=True)


async def admin_broadcast_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    rows = await db.get_broadcast_history(10)
    text = msg.admin_broadcast_history_text(rows)
    await query.edit_message_text(
        text, reply_markup=kb.admin_maintenance_menu(), parse_mode=ParseMode.MARKDOWN
    )


# ══════════════════════════════════════════════
# COMANDOS ADMIN DIRECTOS
# ══════════════════════════════════════════════

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.NOT_ADMIN)
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            msg.ADMIN_ADDDAYS_FORMAT_ERROR, parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        user_id = int(args[0])
        days    = int(args[1])
        if days <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            msg.ADMIN_ADDDAYS_FORMAT_ERROR, parse_mode=ParseMode.MARKDOWN
        )
        return

    new_exp = await db.add_days_to_subscription(user_id, days)
    if new_exp is None:
        await update.message.reply_text(
            msg.ADMIN_ADDDAYS_NOT_FOUND, parse_mode=ParseMode.MARKDOWN
        )
        return

    await db.audit(ADMIN_ID, "adddays", user_id, f"+{days}d")
    await db.log_event("admin_adddays", user_id, f"+{days}d")
    await safe_send(
        context.bot, user_id,
        f"🎁 *El administrador te ha añadido {days} días*\n"
        f"`─────────────────────────`\n"
        f"📅 Nueva fecha: `{new_exp.strftime('%d/%m/%Y %H:%M UTC')}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.reply_text(
        msg.admin_adddays_ok(user_id, days, new_exp), parse_mode=ParseMode.MARKDOWN
    )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.NOT_ADMIN)
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ Uso: `/ban USER_ID [razón]`", parse_mode=ParseMode.MARKDOWN
        )
        return
    user_id = int(args[0])
    reason  = " ".join(args[1:]) if len(args) > 1 else None
    sub     = await db.get_subscription(user_id)
    uname   = sub["username"]  if sub else None
    fname   = sub["full_name"] if sub else None
    await db.add_to_blacklist(user_id, uname, fname, reason, banned_by=ADMIN_ID)
    if sub:
        await kick_user(context.bot, user_id)
        await db.delete_subscription(user_id)
    await db.audit(ADMIN_ID, "ban", user_id, reason)
    await safe_send(context.bot, user_id, msg.BLACKLISTED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(
        msg.admin_banned_ok(user_id), parse_mode=ParseMode.MARKDOWN
    )


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(msg.NOT_ADMIN)
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "❌ Uso: `/unban USER_ID`", parse_mode=ParseMode.MARKDOWN
        )
        return
    user_id = int(args[0])
    removed = await db.remove_from_blacklist(user_id)
    await db.audit(ADMIN_ID, "unban", user_id)
    if removed:
        await update.message.reply_text(
            msg.admin_unbanned_ok(user_id), parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            msg.ADMIN_UNBAN_NOT_FOUND, parse_mode=ParseMode.MARKDOWN
        )


# ══════════════════════════════════════════════
# FALLBACKS UNIVERSALES
# ══════════════════════════════════════════════

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        msg.OPERATION_CANCELLED, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        msg.OPERATION_CANCELLED, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def timeout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.effective_user:
        await safe_send(
            context.bot, update.effective_user.id,
            msg.TIMEOUT_MSG, parse_mode=ParseMode.MARKDOWN
        )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# LÓGICA INTERNA PARA JOBS
# ══════════════════════════════════════════════

async def _cleanup_expired(bot: Bot) -> int:
    expired = await db.get_expired_subscriptions()
    count   = 0
    for sub in expired:
        uid = sub["user_id"]
        await kick_user(bot, uid)
        await db.delete_subscription(uid)
        await db.log_event("expired_kicked", uid)
        await safe_send(bot, uid, msg.subscription_expired_msg(), parse_mode=ParseMode.MARKDOWN)
        count += 1
    if count:
        logger.info("Cleanup: %d usuarios vencidos eliminados", count)
    return count


async def _scan_intruders(bot: Bot) -> int:
    count = 0
    try:
        active = await db.get_active_subscriptions()
        for sub in active:
            uid = sub["user_id"]
            try:
                member = await bot.get_chat_member(CHANNEL_ID, uid)
                if member.status in (ChatMember.LEFT, ChatMember.BANNED):
                    await db.delete_subscription(uid)
                    await db.log_event("ghost_cleaned", uid)
                    count += 1
            except TelegramError as exc:
                logger.warning("get_chat_member %s: %s", uid, exc)
    except TelegramError as exc:
        logger.error("_scan_intruders: %s", exc)
    return count


# ══════════════════════════════════════════════
# JOBS PROGRAMADOS
# ══════════════════════════════════════════════

async def job_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("JOB: cleanup iniciado")
    await _cleanup_expired(context.bot)


async def job_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("JOB: scan_intruders iniciado")
    await _scan_intruders(context.bot)


async def job_warn_3d(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("JOB: warn_3d iniciado")
    subs = await db.get_expiring_soon(days=3, warned_field="warned_3d")
    for sub in subs:
        exp = datetime.fromisoformat(sub["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        dleft = max(0, int((exp - datetime.now(timezone.utc)).total_seconds() // 86400))
        sent  = await safe_send(
            context.bot, sub["user_id"],
            msg.warning_3d(dleft),
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN,
        )
        if sent:
            await db.mark_warned_3d(sub["user_id"])
            await db.log_event("warned_3d", sub["user_id"])


async def job_warn_1d(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("JOB: warn_1d iniciado")
    subs = await db.get_expiring_soon(days=1, warned_field="warned_1d")
    for sub in subs:
        sent = await safe_send(
            context.bot, sub["user_id"],
            msg.warning_1d(),
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN,
        )
        if sent:
            await db.mark_warned_1d(sub["user_id"])
            await db.log_event("warned_1d", sub["user_id"])


async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("JOB: daily_summary iniciado")
    counts      = await db.count_subscriptions()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    new_today     = await db.get_daily_new_users(today_start)
    expired_today = await db.get_daily_expired(today_start)
    await safe_send(
        context.bot, ADMIN_ID,
        msg.daily_summary(counts, new_today, expired_today),
        parse_mode=ParseMode.MARKDOWN,
    )


async def job_process_referral_bonuses(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa bonuses pendientes de referidos que se hayan ganado."""
    pass  # Los bonuses se procesan en tiempo real al activar código


# ══════════════════════════════════════════════
# POST-INIT
# ══════════════════════════════════════════════

async def post_init(application: Application) -> None:
    await db.init_db()
    jq = application.job_queue
    # Cada hora: limpiar vencidos
    jq.run_repeating(job_cleanup,       interval=3600,  first=60,   name="cleanup")
    # Cada 30 min: escanear intrusos
    jq.run_repeating(job_scan,          interval=1800,  first=120,  name="scan")
    # Cada 12h: avisar 3 días
    jq.run_repeating(job_warn_3d,       interval=43200, first=300,  name="warn_3d")
    # Cada 12h: avisar 1 día
    jq.run_repeating(job_warn_1d,       interval=43200, first=360,  name="warn_1d")
    # Cada día a las 08:00 UTC: resumen al admin
    jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time().replace(tzinfo=timezone.utc), name="daily_summary")
    logger.info("✅ Jobs registrados")


# ══════════════════════════════════════════════
# CONSTRUCCIÓN DE CONVERSATION HANDLERS
# ══════════════════════════════════════════════

_FALLBACKS = [
    CallbackQueryHandler(cancel_callback,   pattern="^cancel$"),
    CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
    CallbackQueryHandler(admin_back_callback, pattern="^admin_back$"),
    CommandHandler("cancel", cancel_command),
    CommandHandler("start",  start_handler),
]

_TIMEOUT_STATE = {
    ConversationHandler.TIMEOUT: [
        MessageHandler(filters.ALL, timeout_handler),
        CallbackQueryHandler(timeout_handler),
    ]
}


def _conv(entry_points, states, name):
    return ConversationHandler(
        entry_points=entry_points,
        states={**states, **_TIMEOUT_STATE},
        fallbacks=_FALLBACKS,
        conversation_timeout=300,
        name=name,
        persistent=False,
    )


def build_handlers():
    return [
        # Usuario
        _conv(
            [CallbackQueryHandler(activate_code_start, pattern="^activate_code$")],
            {ST_ACTIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_code_receive)]},
            "conv_activate",
        ),
        _conv(
            [CallbackQueryHandler(renew_code_start, pattern="^renew_code$")],
            {ST_RENEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_code_receive)]},
            "conv_renew",
        ),
        # Admin — generar código
        _conv(
            [CallbackQueryHandler(admin_gen_code_start, pattern="^admin_gen_code$")],
            {ST_ADMIN_GEN: [
                CallbackQueryHandler(admin_gen_code_quick, pattern=r"^admin_quickcode_\d+_\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gen_code_receive),
            ]},
            "conv_admin_gen",
        ),
        # Admin — buscar
        _conv(
            [CallbackQueryHandler(admin_search_start, pattern="^admin_search$")],
            {ST_ADMIN_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_receive)]},
            "conv_admin_search",
        ),
        # Admin — expulsar
        _conv(
            [CallbackQueryHandler(admin_kick_start, pattern="^admin_kick$")],
            {ST_ADMIN_KICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_kick_receive)]},
            "conv_admin_kick",
        ),
        # Admin — banear
        _conv(
            [CallbackQueryHandler(admin_ban_start, pattern="^admin_ban$")],
            {ST_ADMIN_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_receive)]},
            "conv_admin_ban",
        ),
        # Admin — desbanear
        _conv(
            [CallbackQueryHandler(admin_unban_start, pattern="^admin_unban$")],
            {ST_ADMIN_UNBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_receive)]},
            "conv_admin_unban",
        ),
        # Admin — broadcast (2 pasos)
        _conv(
            [CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
            {
                ST_ADMIN_BROADCAST: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_receive)
                ],
                ST_ADMIN_BROADCAST_CONFIRM: [
                    CallbackQueryHandler(admin_broadcast_confirm_callback, pattern="^admin_broadcast_confirm$"),
                ],
            },
            "conv_admin_broadcast",
        ),
    ]


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── ConversationHandlers (primero) ──
    for handler in build_handlers():
        app.add_handler(handler)

    # ── Comandos ──
    app.add_handler(CommandHandler("start",   start_handler))
    app.add_handler(CommandHandler("admin",   admin_command))
    app.add_handler(CommandHandler("adddays", adddays_command))
    app.add_handler(CommandHandler("ban",     ban_command))
    app.add_handler(CommandHandler("unban",   unban_command))

    # ── Callbacks usuario ──
    app.add_handler(CallbackQueryHandler(main_menu_callback,        pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(help_callback,             pattern="^help$"))
    app.add_handler(CallbackQueryHandler(my_subscription_callback,  pattern="^my_subscription$"))
    app.add_handler(CallbackQueryHandler(my_referrals_callback,     pattern="^my_referrals$"))
    app.add_handler(CallbackQueryHandler(my_history_callback,       pattern="^my_history$"))
    app.add_handler(CallbackQueryHandler(get_referral_link_callback,pattern="^get_referral_link$"))
    app.add_handler(CallbackQueryHandler(free_trial_callback,       pattern="^free_trial$"))
    app.add_handler(CallbackQueryHandler(confirm_free_trial_callback,pattern="^confirm_free_trial$"))

    # ── Callbacks admin — panel ──
    app.add_handler(CallbackQueryHandler(admin_back_callback,           pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_refresh_callback,        pattern="^admin_refresh$"))
    app.add_handler(CallbackQueryHandler(admin_list_codes_callback,     pattern="^admin_list_codes$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback,          pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_members_callback,        pattern="^admin_members$"))
    app.add_handler(CallbackQueryHandler(admin_intruders_callback,      pattern="^admin_intruders$"))
    app.add_handler(CallbackQueryHandler(admin_maintenance_callback,    pattern="^admin_maintenance$"))
    app.add_handler(CallbackQueryHandler(admin_blacklist_callback,      pattern="^admin_blacklist$"))
    app.add_handler(CallbackQueryHandler(admin_view_blacklist_callback, pattern="^admin_view_blacklist$"))
    app.add_handler(CallbackQueryHandler(admin_audit_callback,          pattern="^admin_audit$"))

    # ── Callbacks admin — mantenimiento ──
    app.add_handler(CallbackQueryHandler(admin_force_cleanup_callback,     pattern="^admin_force_cleanup$"))
    app.add_handler(CallbackQueryHandler(admin_force_scan_callback,        pattern="^admin_force_scan$"))
    app.add_handler(CallbackQueryHandler(admin_backup_db_callback,         pattern="^admin_backup_db$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_history_callback, pattern="^admin_broadcast_history$"))

    # ── Callbacks admin — confirmaciones ──
    app.add_handler(CallbackQueryHandler(admin_kick_confirm_callback, pattern=r"^admin_kick_confirm_\d+$"))

    # ── Auto-respuesta a texto libre (ÚLTIMO, prioridad mínima) ──
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
        auto_response_handler,
    ))

    logger.info("🚀 DX VIP Bot iniciando...")
    app.run_polling(
        drop_pending_updates=True,
        close_loop=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
