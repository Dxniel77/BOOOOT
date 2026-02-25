"""
bot.py — DX VIP Bot · Lógica principal
Nuevas funciones: soporte con tickets, ruleta semanal, ranking (admin), Mini App Telegram
Sin sistema de referidos.
"""

import logging
import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes,
    filters, JobQueue
)

import database as db
import keyboards as kb
import messages as msg

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
MINIAPP_URL = os.getenv("MINIAPP_URL", "")  # URL pública de tu Mini App

# ── ConversationHandler states ──
(
    STATE_ACTIVATE,
    STATE_RENEW,
    STATE_GEN_CODE,
    STATE_CUSTOM_CODE,
    STATE_ADDDAYS,
    STATE_BAN_INPUT,
    STATE_UNBAN_INPUT,
    STATE_BROADCAST,
    STATE_TICKET_SUBJECT,
    STATE_TICKET_MESSAGE,
    STATE_TICKET_REPLY_USER,
    STATE_ADM_TICKET_REPLY,
    STATE_SEARCH,
) = range(13)


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def fmt_expiry(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %H:%M UTC")

def days_left(expiry_str: str) -> int:
    exp = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return max(0, (exp - utc_now()).days)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def kick_from_channel(bot, user_id: int):
    try:
        await bot.ban_chat_member(CHANNEL_ID, user_id)
        await bot.unban_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        logger.warning(f"kick_from_channel error for {user_id}: {e}")

async def add_to_channel(bot, user_id: int):
    try:
        link = await bot.create_chat_invite_link(
            CHANNEL_ID, member_limit=1,
            expire_date=utc_now() + timedelta(minutes=5)
        )
        return link.invite_link
    except Exception as e:
        logger.warning(f"add_to_channel error: {e}")
        return None

def gen_random_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "VIP-" + "".join(random.choices(chars, k=6))

async def unique_code() -> str:
    for _ in range(30):
        code = gen_random_code()
        if not await db.code_exists(code):
            return code
    return "VIP-" + secrets.token_hex(3).upper()


# ──────────────────────────────────────────────────────────────
# MIDDLEWARE — banned check
# ──────────────────────────────────────────────────────────────
async def check_banned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Retorna True si el usuario está baneado (y ya se le notificó)."""
    user = update.effective_user
    if user and await db.is_banned(user.id):
        target = update.message or (update.callback_query and update.callback_query.message)
        if target:
            await target.reply_text(msg.already_banned(), parse_mode=ParseMode.MARKDOWN)
        return True
    return False


# ──────────────────────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    user = update.effective_user
    await update.message.reply_text(
        msg.welcome(user.first_name),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────
# MAIN MENU callbacks
# ──────────────────────────────────────────────────────────────
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user
    await q.edit_message_text(
        msg.welcome(user.first_name),
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────
# MEMBRESÍA
# ──────────────────────────────────────────────────────────────
async def membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user
    sub = await db.get_subscription(user.id)
    if not sub:
        await q.edit_message_text(msg.no_membership(), reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    dl = days_left(sub["expiry"])
    expiry_fmt = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    joined     = sub["joined_at"][:10]
    card_text  = msg.membership_card(
        user.first_name, expiry_fmt, dl,
        sub["total_days"], sub["renewals"], joined
    )
    await q.edit_message_text(
        card_text,
        reply_markup=kb.membership_menu(MINIAPP_URL if MINIAPP_URL else None),
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────
# ACTIVAR CÓDIGO
# ──────────────────────────────────────────────────────────────
async def activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔑 *Activar código VIP*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nEscribe tu código VIP:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_ACTIVATE

async def activate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    user  = update.effective_user
    code  = update.message.text.strip().upper()
    row   = await db.get_code(code)

    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text(msg.code_not_found(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    days     = row["days"]
    sub      = await db.get_subscription(user.id)
    if sub:
        current_exp = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        new_exp = max(current_exp, utc_now()) + timedelta(days=days)
    else:
        new_exp = utc_now() + timedelta(days=days)

    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)

    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)

    link = await add_to_channel(context.bot, user.id)
    reply = msg.activation_success(user.first_name, days, fmt_expiry(new_exp))
    if link:
        reply += f"\n\n🔗 [Accede al canal]({link})"

    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    await db.log_event("activate", user.id, f"code={code} days={days}")
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────
# RENOVAR
# ──────────────────────────────────────────────────────────────
async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔄 *Renovar acceso*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nEscribe tu código de renovación:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_RENEW

async def renew_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip().upper()
    row  = await db.get_code(code)

    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text(msg.code_not_found(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    sub = await db.get_subscription(user.id)
    if not sub:
        await update.message.reply_text(
            "⚠️ No tienes membresía activa. Usa *Activar código* primero.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    days = row["days"]
    current_exp = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    new_exp = max(current_exp, utc_now()) + timedelta(days=days)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)
    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)

    await update.message.reply_text(
        msg.renewal_success(days, fmt_expiry(new_exp)),
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu()
    )
    await db.log_event("renew", user.id, f"code={code} days={days}")
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────
# PRUEBA GRATIS
# ──────────────────────────────────────────────────────────────
async def free_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user

    if await db.has_used_trial(user.id):
        await q.edit_message_text(msg.free_trial_already_used(), reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    new_exp = utc_now() + timedelta(days=2)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, 2, "FREE_TRIAL")
    await db.mark_trial_used(user.id)

    link = await add_to_channel(context.bot, user.id)
    reply = msg.free_trial_success(fmt_expiry(new_exp))
    if link:
        reply += f"\n\n🔗 [Accede al canal]({link})"

    await q.edit_message_text(reply, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    await db.log_event("trial", user.id)


# ──────────────────────────────────────────────────────────────
# HISTORIAL
# ──────────────────────────────────────────────────────────────
async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user    = q.from_user
    events  = await db.get_user_history(user.id)
    txt     = msg.history_header(user.first_name)
    if not events:
        txt += "_Sin actividad registrada._"
    for e in events:
        txt += msg.history_item(e["event"], e["data"] or "", e["created_at"][:16])
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back() if is_admin(user.id) else kb.main_menu(), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# 🎰 RULETA SEMANAL
# ──────────────────────────────────────────────────────────────
RULETA_OPTIONS = [1, 1, 2, 2, 3, 3, 3, 5, 5, 7]

async def ruleta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user

    sub = await db.get_subscription(user.id)
    if not sub or days_left(sub["expiry"]) <= 0:
        await q.edit_message_text(msg.ruleta_no_membership(), reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    can_play = await db.can_play_ruleta(user.id)
    if can_play:
        await q.edit_message_text(msg.ruleta_menu(True), reply_markup=kb.ruleta_play(), parse_mode=ParseMode.MARKDOWN)
    else:
        history = await db.get_ruleta_history(user.id)
        last_play = history[0]["played_at"] if history else ""
        if last_play:
            last_dt = datetime.strptime(last_play, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            next_dt = last_dt + timedelta(days=7)
            next_str = next_dt.strftime("%d/%m/%Y %H:%M UTC")
        else:
            next_str = "pronto"
        await q.edit_message_text(msg.ruleta_menu(False, next_str), reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)

async def ruleta_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("🎰 Girando...")
    user = q.from_user

    can_play = await db.can_play_ruleta(user.id)
    if not can_play:
        await q.answer("⏳ Ya jugaste esta semana.", show_alert=True)
        return

    await q.edit_message_text(msg.ruleta_spinning(), parse_mode=ParseMode.MARKDOWN)

    import asyncio
    await asyncio.sleep(2)

    days_won = random.choice(RULETA_OPTIONS)
    ok = await db.add_days_to_subscription(user.id, days_won)
    if not ok:
        await q.edit_message_text("⚠️ Error al procesar tu premio. Intenta de nuevo.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    await db.log_ruleta(user.id, days_won)
    await db.log_event("ruleta", user.id, f"won={days_won}")

    sub = await db.get_subscription(user.id)
    new_expiry = fmt_expiry(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc))
    await q.edit_message_text(msg.ruleta_result(days_won, new_expiry), reply_markup=kb.ruleta_result(), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# 🎟️ SOPORTE / TICKETS
# ──────────────────────────────────────────────────────────────
async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(msg.support_menu_text(), reply_markup=kb.support_menu(), parse_mode=ParseMode.MARKDOWN)

# -- Nuevo ticket --
async def ticket_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(msg.ticket_ask_subject(), reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_SUBJECT

async def ticket_subject_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip()[:100]
    context.user_data["ticket_subject"] = subject
    await update.message.reply_text(msg.ticket_ask_message(), reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_MESSAGE

async def ticket_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    subject = context.user_data.get("ticket_subject", "Sin asunto")
    content = update.message.text.strip()

    ticket_id = await db.create_ticket(user.id, user.username or "", user.first_name, subject)
    await db.add_ticket_message(ticket_id, user.id, content, is_admin=False)
    await db.log_event("ticket", user.id, f"id={ticket_id}")

    await update.message.reply_text(
        msg.ticket_created(ticket_id, subject),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.main_menu()
    )

    # Notificar admin
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🎟️ *Nuevo ticket #{ticket_id:04d}*\n"
            f"👤 {user.first_name} (`{user.id}`)\n"
            f"📌 _{subject}_\n\n{content}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_ticket_actions(ticket_id, True)
        )
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END

# -- Listar mis tickets --
async def ticket_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user    = q.from_user
    tickets = await db.get_user_tickets(user.id)
    txt     = msg.ticket_list_header()
    if not tickets:
        txt += "_No tienes tickets registrados._"
    for t in tickets:
        txt += msg.ticket_item(t["id"], t["subject"], t["status"], t["updated_at"][:16])

    # Botones para cada ticket abierto
    buttons = []
    for t in tickets[:5]:
        if t["status"] == "open":
            buttons.append([InlineKeyboardButton(f"📬 Ver #{t['id']:04d}", callback_data=f"ticket_view_{t['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Menú principal", callback_data="main_menu")])
    await q.edit_message_text(txt[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def ticket_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    ticket    = await db.get_ticket(ticket_id)
    messages_ = await db.get_ticket_messages(ticket_id)
    if not ticket:
        await q.answer("Ticket no encontrado.", show_alert=True)
        return
    await q.edit_message_text(
        msg.ticket_detail(ticket_id, ticket["subject"], ticket["status"], messages_),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.ticket_user_actions(ticket_id, ticket["status"] == "open")
    )

# -- Responder ticket (usuario) --
async def ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    context.user_data["reply_ticket_id"] = ticket_id
    await q.edit_message_text(
        f"💬 Responder ticket *#{ticket_id:04d}*\n\nEscribe tu mensaje:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.cancel_keyboard()
    )
    return STATE_TICKET_REPLY_USER

async def ticket_reply_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user      = update.effective_user
    ticket_id = context.user_data.get("reply_ticket_id")
    text      = update.message.text.strip()

    await db.add_ticket_message(ticket_id, user.id, text, is_admin=False)
    await update.message.reply_text(msg.ticket_reply_sent(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.support_menu())

    try:
        ticket = await db.get_ticket(ticket_id)
        await context.bot.send_message(
            ADMIN_ID,
            f"💬 *Respuesta en ticket #{ticket_id:04d}*\n"
            f"👤 {user.first_name}: {text}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_ticket_actions(ticket_id, True)
        )
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END

async def ticket_close_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.close_ticket(ticket_id)
    await q.edit_message_text(msg.ticket_closed_user(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.support_menu())

async def ticket_reopen_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.reopen_ticket(ticket_id)
    await q.answer("🔄 Ticket reabierto.", show_alert=True)


# ──────────────────────────────────────────────────────────────
# ADMIN — Panel
# ──────────────────────────────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    stats = await db.get_stats_summary()
    await update.message.reply_text(
        msg.admin_panel_text(stats),
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    q = update.callback_query
    await q.answer()
    stats = await db.get_stats_summary()
    await q.edit_message_text(
        msg.admin_panel_text(stats),
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )


# ── Generar código ──
async def adm_gen_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔑 *Generar código VIP*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Atajos rápidos abajo, o escribe:\n"
        "`DIAS USOS` para código aleatorio\n"
        "`CODIGO DIAS USOS [NOTA]` para personalizado",
        reply_markup=kb.admin_gen_code_shortcuts(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_GEN_CODE

async def adm_gen_code_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    days_map = {"7": 7, "15": 15, "30": 30, "60": 60, "90": 90}
    d = q.data.split("_")[-1]
    days = days_map.get(d, 30)
    code = await unique_code()
    await db.create_code(code, days, 1)
    await db.audit(ADMIN_ID, "gen_code", code, f"{days}d 1uso")
    await q.edit_message_text(
        msg.admin_code_created(code, days, 1, ""),
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_gen_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    parts = update.message.text.strip().split()
    try:
        if len(parts) == 2:
            days, uses = int(parts[0]), int(parts[1])
            code = await unique_code()
            note = ""
        elif len(parts) >= 3:
            try:
                days, uses = int(parts[0]), int(parts[1])
                code = await unique_code()
                note = " ".join(parts[2:])
            except ValueError:
                code = parts[0].upper()
                days = int(parts[1])
                uses = int(parts[2])
                note = " ".join(parts[3:]) if len(parts) > 3 else ""
        else:
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("⚠️ Formato inválido. Ejemplo: `30 5` o `VIP30 30 1 Promo`", parse_mode=ParseMode.MARKDOWN)
        return STATE_GEN_CODE

    await db.create_code(code, days, uses, note)
    await db.audit(ADMIN_ID, "gen_code", code, f"{days}d {uses}usos")
    await update.message.reply_text(
        msg.admin_code_created(code, days, uses, note),
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ── Listar códigos ──
async def adm_list_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    codes = await db.list_codes()
    await q.edit_message_text(msg.admin_codes_list(codes), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Miembros ──
async def adm_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    members = await db.get_active_members()
    await q.edit_message_text(msg.admin_members_list(members), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Estadísticas ──
async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    stats   = await db.get_stats_summary()
    members = await db.get_active_members()
    await q.edit_message_text(msg.admin_stats(stats, members), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Ranking ──
async def adm_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    ranking = await db.get_ranking(10)
    await q.edit_message_text(msg.admin_ranking(ranking), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Blacklist ──
async def adm_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🚫 *Gestión de Blacklist*", reply_markup=kb.admin_blacklist_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_blacklist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    bl = await db.get_blacklist()
    await q.edit_message_text(msg.admin_blacklist_list(bl), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ban_input_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🚫 Escribe: `USER_ID razón`", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_BAN_INPUT

async def adm_ban_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split(maxsplit=1)
    uid   = int(parts[0])
    reason = parts[1] if len(parts) > 1 else ""
    await db.ban_user(uid, reason, ADMIN_ID)
    await db.audit(ADMIN_ID, "ban", str(uid), reason)
    await kick_from_channel(context.bot, uid)
    await update.message.reply_text(msg.admin_ban_success(uid), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(uid, "🚫 Tu acceso ha sido suspendido.")
    except Exception:
        pass
    return ConversationHandler.END

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /ban USER_ID [razón]")
        return
    uid    = int(args[0])
    reason = " ".join(args[1:]) if len(args) > 1 else ""
    await db.ban_user(uid, reason, ADMIN_ID)
    await db.audit(ADMIN_ID, "ban", str(uid), reason)
    await kick_from_channel(context.bot, uid)
    await update.message.reply_text(msg.admin_ban_success(uid), parse_mode=ParseMode.MARKDOWN)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Uso: /unban USER_ID")
        return
    uid = int(context.args[0])
    await db.unban_user(uid)
    await db.audit(ADMIN_ID, "unban", str(uid))
    await update.message.reply_text(msg.admin_unban_success(uid), parse_mode=ParseMode.MARKDOWN)

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /adddays USER_ID DIAS")
        return
    uid, days = int(args[0]), int(args[1])
    ok = await db.add_days_to_subscription(uid, days)
    if ok:
        sub = await db.get_subscription(uid)
        new_exp = fmt_expiry(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc))
        await update.message.reply_text(msg.admin_adddays_success(uid, days, new_exp), parse_mode=ParseMode.MARKDOWN)
        await db.audit(ADMIN_ID, "adddays", str(uid), f"+{days}")
    else:
        await update.message.reply_text("⚠️ Usuario sin membresía activa.")


# ── Admin Tickets ──
async def adm_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🎟️ *Soporte — Tickets*", reply_markup=kb.admin_tickets_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tickets = await db.get_open_tickets()
    buttons = []
    for t in tickets[:8]:
        buttons.append([InlineKeyboardButton(f"📬 #{t['id']:04d} — {t['subject'][:30]}", callback_data=f"adm_tview_{t['id']}")])
    buttons.append([InlineKeyboardButton("« Tickets", callback_data="adm_tickets")])
    await q.edit_message_text(
        msg.admin_tickets_list(tickets, open_only=True),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_tickets_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tickets = await db.get_all_tickets(30)
    buttons = []
    for t in tickets[:8]:
        st = "📬" if t["status"] == "open" else "✅"
        buttons.append([InlineKeyboardButton(f"{st} #{t['id']:04d} — {t['subject'][:25]}", callback_data=f"adm_tview_{t['id']}")])
    buttons.append([InlineKeyboardButton("« Tickets", callback_data="adm_tickets")])
    await q.edit_message_text(
        msg.admin_tickets_list(tickets, open_only=False),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_ticket_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    ticket    = await db.get_ticket(ticket_id)
    messages_ = await db.get_ticket_messages(ticket_id)
    if not ticket:
        await q.answer("Ticket no encontrado.", show_alert=True)
        return
    await q.edit_message_text(
        msg.admin_ticket_detail(ticket, messages_),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_ticket_actions(ticket_id, ticket["status"] == "open")
    )

async def adm_ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    context.user_data["adm_reply_ticket"] = ticket_id
    await q.edit_message_text(
        f"💬 Responder ticket *#{ticket_id:04d}*\n\nEscribe tu respuesta:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.cancel_keyboard()
    )
    return STATE_ADM_TICKET_REPLY

async def adm_ticket_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket_id = context.user_data.get("adm_reply_ticket")
    text      = update.message.text.strip()

    await db.add_ticket_message(ticket_id, ADMIN_ID, text, is_admin=True)
    await db.audit(ADMIN_ID, "ticket_reply", str(ticket_id))
    await update.message.reply_text(msg.admin_ticket_reply_sent(ticket_id), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())

    ticket = await db.get_ticket(ticket_id)
    if ticket:
        try:
            await context.bot.send_message(
                ticket["user_id"],
                msg.ticket_new_reply_user(ticket_id, text),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    context.user_data.clear()
    return ConversationHandler.END

async def adm_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.close_ticket(ticket_id)
    await db.audit(ADMIN_ID, "ticket_close", str(ticket_id))
    await q.answer("✅ Ticket cerrado.", show_alert=True)
    ticket    = await db.get_ticket(ticket_id)
    messages_ = await db.get_ticket_messages(ticket_id)
    await q.edit_message_text(
        msg.admin_ticket_detail(ticket, messages_),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb.admin_ticket_actions(ticket_id, False)
    )

async def adm_ticket_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.reopen_ticket(ticket_id)
    await q.answer("🔄 Ticket reabierto.", show_alert=True)


# ── Broadcast ──
async def adm_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📢 *Broadcast masivo*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nEscribe el mensaje a enviar:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_BROADCAST

async def adm_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["broadcast_msg"] = text
    await update.message.reply_text(
        msg.admin_broadcast_preview(text),
        reply_markup=kb.confirm_action("adm_broadcast_confirm"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    text    = context.user_data.get("broadcast_msg", "")
    members = await db.get_active_members()
    sent = failed = 0
    for m in members:
        try:
            await context.bot.send_message(m["user_id"], text, parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1
    await db.log_broadcast(text, sent, failed)
    await db.audit(ADMIN_ID, "broadcast", "", f"sent={sent} failed={failed}")
    context.user_data.clear()
    await q.edit_message_text(msg.admin_broadcast_done(sent, failed), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Mantenimiento ──
async def adm_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🔧 *Mantenimiento*", reply_markup=kb.admin_maintenance_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_clean_expired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("🧹 Limpiando...")
    expired = await db.get_expired_members()
    count = 0
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        count += 1
    await db.audit(ADMIN_ID, "clean_expired", "", f"removed={count}")
    await q.edit_message_text(f"✅ *Limpieza completada*\nExpulsados: *{count}*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    try:
        from database import DB_PATH
        await context.bot.send_document(ADMIN_ID, document=open(DB_PATH, "rb"), filename="dx_vip_backup.db")
    except Exception as e:
        await q.answer(f"Error: {e}", show_alert=True)

async def adm_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    logs = await db.get_audit_log(30)
    txt  = f"📋 *Log de auditoría*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for l in logs:
        txt += f"`{l['created_at'][:16]}` — *{l['action']}* {l['target'] or ''}\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    history = await db.get_broadcast_history(10)
    txt = f"📜 *Historial de broadcasts*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for b in history:
        txt += f"`{b['created_at'][:16]}` → {b['sent_to']} enviados, {b['failed']} fallidos\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_scan_intruders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("👻 Escaneando...")
    await q.edit_message_text(
        "👻 *Scan de intrusos completado*\n\n_Funcionalidad disponible via bot.get_chat_members en la versión de producción._",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────
# JOBS AUTOMÁTICOS
# ──────────────────────────────────────────────────────────────
async def job_clean_expired(context: ContextTypes.DEFAULT_TYPE):
    expired = await db.get_expired_members()
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        try:
            await context.bot.send_message(m["user_id"], msg.expired_notification(), parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE):
    for hours, days_label in [(72, 3), (24, 1)]:
        expiring = await db.get_expiring_soon(hours)
        for m in expiring:
            dl = days_left(m["expiry"])
            try:
                await context.bot.send_message(
                    m["user_id"],
                    msg.expiry_warning(dl),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb.main_menu()
                )
            except Exception:
                pass

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    stats = await db.get_stats_summary()
    try:
        await context.bot.send_message(ADMIN_ID, msg.daily_summary(stats), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# AUTO-RESPUESTA
# ──────────────────────────────────────────────────────────────
async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return
    user = update.effective_user
    text = (update.message.text or "").lower()

    replies = {
        ("hola", "hi", "buenas", "ola"): f"👋 ¡Hola {user.first_name}! Usa el menú para gestionar tu acceso.",
        ("precio", "costo", "valor", "plan"): "💎 Contacta al admin para información sobre planes VIP.",
        ("ayuda", "help", "soporte"): "🎟️ Usa el botón *Soporte* del menú para abrir un ticket.",
        ("canal", "acceso", "link"): "🔑 Activa tu código VIP para obtener acceso al canal.",
    }
    for keywords, reply in replies.items():
        if any(k in text for k in keywords):
            await update.message.reply_text(reply, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
            return

    await update.message.reply_text(
        f"💬 ¿En qué puedo ayudarte, {user.first_name}?\nUsa el menú o abre un ticket de soporte.",
        reply_markup=kb.main_menu()
    )


# ──────────────────────────────────────────────────────────────
# MINI APP — API endpoint (si usas aiohttp/FastAPI por separado)
# Este handler responde al WebApp con los datos de membresía
# ──────────────────────────────────────────────────────────────
async def miniapp_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Endpoint alternativo: el usuario pulsa el botón Mini App,
    la web llama a /api/membership en tu servidor.
    Aquí solo dejamos el comando /mydata como fallback.
    """
    user = update.effective_user
    sub  = await db.get_subscription(user.id)
    if not sub:
        await update.message.reply_text("Sin membresía activa.")
        return
    dl = days_left(sub["expiry"])
    import json
    from datetime import timezone
    expiry_ts = int(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=timezone.utc).timestamp() * 1000)
    data = {
        "active": True,
        "days_left": dl,
        "total_days": sub["total_days"],
        "expiry_ts": expiry_ts,
        "join_date": sub["joined_at"],
        "plan": f"VIP · {sub['total_days']}D"
    }
    await update.message.reply_text(f"```json\n{json.dumps(data, indent=2)}\n```", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    import asyncio
    asyncio.get_event_loop().run_until_complete(db.init_db())

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation: Activar código ──
    conv_activate = ConversationHandler(
        entry_points=[CallbackQueryHandler(activate_start, pattern="^activate$")],
        states={STATE_ACTIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_code)]},
        fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
        conversation_timeout=300
    )

    # ── Conversation: Renovar ──
    conv_renew = ConversationHandler(
        entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
        states={STATE_RENEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_code)]},
        fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
        conversation_timeout=300
    )

    # ── Conversation: Admin generar código ──
    conv_gen_code = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_gen_code_menu, pattern="^adm_gen_code$")],
        states={
            STATE_GEN_CODE: [
                CallbackQueryHandler(adm_gen_code_quick, pattern="^adm_quick_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gen_code_input)
            ]
        },
        fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
        conversation_timeout=300
    )

    # ── Conversation: Admin ban input ──
    conv_ban = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_ban_input_start, pattern="^adm_ban_input$")],
        states={STATE_BAN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_input_received)]},
        fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
        conversation_timeout=300
    )

    # ── Conversation: Broadcast ──
    conv_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_broadcast_start, pattern="^adm_broadcast$")],
        states={STATE_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_preview)]},
        fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
        conversation_timeout=300
    )

    # ── Conversation: Nuevo ticket (usuario) ──
    conv_ticket_new = ConversationHandler(
        entry_points=[CallbackQueryHandler(ticket_new_start, pattern="^ticket_new$")],
        states={
            STATE_TICKET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_subject_received)],
            STATE_TICKET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_message_received)],
        },
        fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
        conversation_timeout=300
    )

    # ── Conversation: Responder ticket (usuario) ──
    conv_ticket_reply_user = ConversationHandler(
        entry_points=[CallbackQueryHandler(ticket_reply_start, pattern="^ticket_reply_")],
        states={STATE_TICKET_REPLY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_reply_user_message)]},
        fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
        conversation_timeout=300
    )

    # ── Conversation: Admin responder ticket ──
    conv_adm_ticket_reply = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_ticket_reply_start, pattern="^adm_ticket_reply_")],
        states={STATE_ADM_TICKET_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ticket_reply_message)]},
        fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
        conversation_timeout=300
    )

    # ── Registrar handlers ──
    for conv in [conv_activate, conv_renew, conv_gen_code, conv_ban,
                 conv_broadcast, conv_ticket_new, conv_ticket_reply_user, conv_adm_ticket_reply]:
        app.add_handler(conv)

    # Comandos
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("adddays", adddays_command))
    app.add_handler(CommandHandler("mydata", miniapp_data_command))

    # Callbacks — usuario
    app.add_handler(CallbackQueryHandler(main_menu_callback,    pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(free_trial_callback,   pattern="^free_trial$"))
    app.add_handler(CallbackQueryHandler(history_callback,      pattern="^history$"))
    app.add_handler(CallbackQueryHandler(ruleta_callback,       pattern="^ruleta$"))
    app.add_handler(CallbackQueryHandler(ruleta_spin,           pattern="^ruleta_spin$"))
    app.add_handler(CallbackQueryHandler(support_callback,      pattern="^support$"))
    app.add_handler(CallbackQueryHandler(ticket_list_callback,  pattern="^ticket_list$"))
    app.add_handler(CallbackQueryHandler(ticket_view_callback,  pattern="^ticket_view_"))
    app.add_handler(CallbackQueryHandler(ticket_close_user,     pattern="^ticket_close_"))
    app.add_handler(CallbackQueryHandler(ticket_reopen_user,    pattern="^ticket_reopen_"))

    # Callbacks — admin
    app.add_handler(CallbackQueryHandler(admin_panel_callback,  pattern="^adm_panel$"))
    app.add_handler(CallbackQueryHandler(adm_list_codes,        pattern="^adm_list_codes$"))
    app.add_handler(CallbackQueryHandler(adm_members,           pattern="^adm_members$"))
    app.add_handler(CallbackQueryHandler(adm_stats,             pattern="^adm_stats$"))
    app.add_handler(CallbackQueryHandler(adm_ranking,           pattern="^adm_ranking$"))
    app.add_handler(CallbackQueryHandler(adm_blacklist,         pattern="^adm_blacklist$"))
    app.add_handler(CallbackQueryHandler(adm_blacklist_list,    pattern="^adm_blacklist_list$"))
    app.add_handler(CallbackQueryHandler(adm_maintenance,       pattern="^adm_maintenance$"))
    app.add_handler(CallbackQueryHandler(adm_clean_expired,     pattern="^adm_clean_expired$"))
    app.add_handler(CallbackQueryHandler(adm_backup,            pattern="^adm_backup$"))
    app.add_handler(CallbackQueryHandler(adm_audit_log,         pattern="^adm_audit_log$"))
    app.add_handler(CallbackQueryHandler(adm_broadcast_history, pattern="^adm_broadcast_history$"))
    app.add_handler(CallbackQueryHandler(adm_scan_intruders,    pattern="^adm_scan_intruders$"))
    app.add_handler(CallbackQueryHandler(adm_broadcast_confirm, pattern="^adm_broadcast_confirm$"))
    app.add_handler(CallbackQueryHandler(adm_tickets,           pattern="^adm_tickets$"))
    app.add_handler(CallbackQueryHandler(adm_tickets_open,      pattern="^adm_tickets_open$"))
    app.add_handler(CallbackQueryHandler(adm_tickets_all,       pattern="^adm_tickets_all$"))
    app.add_handler(CallbackQueryHandler(adm_ticket_view,       pattern="^adm_tview_"))
    app.add_handler(CallbackQueryHandler(adm_ticket_close,      pattern="^adm_ticket_close_"))
    app.add_handler(CallbackQueryHandler(adm_ticket_reopen,     pattern="^adm_ticket_reopen_"))

    # Auto-respuesta
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply))

    # Jobs
    jq: JobQueue = app.job_queue
    jq.run_repeating(job_clean_expired,  interval=3600,   first=60)
    jq.run_repeating(job_warn_expiring,  interval=43200,  first=120)
    jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time())

    logger.info("🚀 DX VIP Bot iniciado")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
