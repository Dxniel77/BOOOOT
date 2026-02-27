"""
bot.py — VIP Bot · Lógica principal
Funciones: activar código, renovar, membresía (Mini App directa),
           prueba gratis 30 días, tickets, ranking, multi-admin,
           broadcast segmentado, exportar CSV, códigos con expiración.
Sin ruleta semanal.
"""

import hashlib
import hmac
import io
import json
import logging
import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, unquote

from aiohttp import web

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003738953503"))
FREE_TRIAL_DAYS = 30
# Railway expone la variable PORT automáticamente
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))


# ──────────────────────────────────────────────────────────────
# HTTP API SERVER (para Mini App)
# ──────────────────────────────────────────────────────────────
def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """Verifica la firma de Telegram initData y retorna el user dict o None."""
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
        hash_val = params.pop("hash", "")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        user_str = params.get("user", "{}")
        return json.loads(unquote(user_str))
    except Exception:
        return None


async def api_user_info(request: web.Request) -> web.Response:
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=cors_headers)

    init_data = request.rel_url.query.get("initData", "")
    user = None
    uid = 0

    if init_data:
        user = verify_telegram_init_data(init_data, BOT_TOKEN or "")
        if user:
            uid = user.get("id", 0)
        if uid == 0:
            try:
                params = dict(parse_qsl(init_data, keep_blank_values=True))
                user_raw = json.loads(unquote(params.get("user", "{}")))
                uid = user_raw.get("id", 0)
                if uid:
                    user = user_raw
            except Exception:
                pass

    if uid == 0:
        try:
            uid = int(request.rel_url.query.get("user_id", "0"))
        except ValueError:
            pass

    if uid == 0:
        return web.json_response({"error": "missing user_id"}, status=400, headers=cors_headers)

    sub = await db.get_subscription(uid)
    if not sub:
        return web.json_response({
            "has_membership": False,
            "user_id": uid,
            "first_name": user.get("first_name", "") if user else "",
        }, headers=cors_headers)

    expiry_dt = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    now_dt = datetime.now(timezone.utc)
    seconds_left = max(0, int((expiry_dt - now_dt).total_seconds()))

    return web.json_response({
        "has_membership": True,
        "user_id": uid,
        "first_name": sub["first_name"] or (user.get("first_name", "") if user else ""),
        "username": sub["username"] or "",
        "expiry": sub["expiry"],
        "expires_at_ts": int(expiry_dt.timestamp() * 1000),  # ms para JS
        "seconds_left": seconds_left,
        "total_days": sub["total_days"] or 0,
        "is_expired": now_dt > expiry_dt,
    }, headers=cors_headers)


async def start_api_server():
    app_http = web.Application()
    app_http.router.add_route("GET",     "/api/user_info", api_user_info)
    app_http.router.add_route("OPTIONS", "/api/user_info", api_user_info)
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    logger.info(f"🌐 API HTTP corriendo en :{API_PORT}")

# ── States ──
(
    STATE_ACTIVATE,
    STATE_RENEW,
    STATE_GEN_CODE,
    STATE_BAN_INPUT,
    STATE_UNBAN_INPUT,
    STATE_BROADCAST_MSG,
    STATE_TICKET_SUBJECT,
    STATE_TICKET_MESSAGE,
    STATE_TICKET_REPLY_USER,
    STATE_ADM_TICKET_REPLY,
    STATE_ADD_ADMIN,
    STATE_REMOVE_ADMIN,
    STATE_ADDDAYS_INPUT,
) = range(13)

# Broadcast segment state
BROADCAST_FILTER: dict = {}


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

async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    admin_ids = await db.get_all_admin_ids()
    return user_id in admin_ids

async def kick_from_channel(bot, user_id: int):
    try:
        await bot.ban_chat_member(CHANNEL_ID, user_id)
        await bot.unban_chat_member(CHANNEL_ID, user_id)
        logger.info(f"Kicked user {user_id} from channel")
    except TelegramError as e:
        logger.warning(f"kick_from_channel {user_id}: {e}")

async def add_to_channel(bot, user_id: int) -> str | None:
    try:
        link = await bot.create_chat_invite_link(
            CHANNEL_ID, member_limit=1,
            expire_date=utc_now() + timedelta(minutes=5)
        )
        return link.invite_link
    except TelegramError as e:
        logger.warning(f"add_to_channel {user_id}: {e}")
        return None

async def notify_user(bot, user_id: int, text: str, **kwargs):
    """Envía mensaje al usuario silenciosamente si falla."""
    try:
        await bot.send_message(user_id, text, **kwargs)
    except TelegramError as e:
        logger.warning(f"notify_user {user_id}: {e}")

async def unique_code() -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "VIP-" + "".join(random.choices(chars, k=6))
        if not await db.code_exists(code):
            return code
    return "VIP-" + secrets.token_hex(4).upper()


# ──────────────────────────────────────────────────────────────
# BANNED CHECK
# ──────────────────────────────────────────────────────────────
async def check_banned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if await db.is_banned(user.id):
        target = update.message or (update.callback_query and update.callback_query.message)
        if target:
            try:
                await target.reply_text(msg.already_banned(), parse_mode=ParseMode.MARKDOWN)
            except TelegramError:
                pass
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
# MENÚ PRINCIPAL
# ──────────────────────────────────────────────────────────────
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        msg.welcome(q.from_user.first_name),
        reply_markup=kb.main_menu(),
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
    user = update.effective_user
    code = update.message.text.strip().upper()

    try:
        row = await db.get_code(code)
    except Exception as e:
        logger.error(f"activate_code db error: {e}")
        await update.message.reply_text("⚠️ Error interno. Intenta de nuevo.", reply_markup=kb.main_menu())
        return ConversationHandler.END

    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text(msg.code_not_found(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
        return ConversationHandler.END

    days    = row["days"]
    sub     = await db.get_subscription(user.id)
    new_exp = (max(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc), utc_now()) + timedelta(days=days)) if sub else (utc_now() + timedelta(days=days))
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)
    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)

    link  = await add_to_channel(context.bot, user.id)
    reply = msg.activation_success(user.first_name, days, fmt_expiry(new_exp))
    if link:
        reply += f"\n\n🔗 [Accede al canal]({link})"

    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    await db.log_event("activate", user.id, f"code={code} days={days}")
    logger.info(f"User {user.id} activated code {code} (+{days}d)")
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
        await update.message.reply_text(msg.code_not_found(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
        return ConversationHandler.END

    sub = await db.get_subscription(user.id)
    if not sub:
        await update.message.reply_text(
            "⚠️ No tienes membresía activa. Usa *Activar código* primero.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu()
        )
        return ConversationHandler.END

    days    = row["days"]
    new_exp = max(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc), utc_now()) + timedelta(days=days)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)
    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)

    await update.message.reply_text(msg.renewal_success(days, fmt_expiry(new_exp)), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    await db.log_event("renew", user.id, f"code={code} days={days}")
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────
# PRUEBA GRATIS — 30 DÍAS, SOLO PRIMERA VEZ
# ──────────────────────────────────────────────────────────────
async def free_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q    = update.callback_query
    await q.answer()
    user = q.from_user

    if await db.has_used_trial(user.id):
        await q.edit_message_text(msg.free_trial_already_used(), reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    new_exp = utc_now() + timedelta(days=FREE_TRIAL_DAYS)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, FREE_TRIAL_DAYS, "FREE_TRIAL")
    await db.mark_trial_used(user.id)

    link  = await add_to_channel(context.bot, user.id)
    reply = msg.free_trial_success(fmt_expiry(new_exp))
    if link:
        reply += f"\n\n🔗 [Accede al canal]({link})"

    await q.edit_message_text(reply, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    await db.log_event("trial", user.id, f"days={FREE_TRIAL_DAYS}")
    logger.info(f"User {user.id} activated free trial ({FREE_TRIAL_DAYS}d)")


# ──────────────────────────────────────────────────────────────
# HISTORIAL
# ──────────────────────────────────────────────────────────────
async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q      = update.callback_query
    await q.answer()
    user   = q.from_user
    events = await db.get_user_history(user.id)
    txt    = msg.history_header(user.first_name)
    if not events:
        txt += "_Sin actividad registrada._"
    for e in events:
        txt += msg.history_item(e["event"], e["data"] or "", e["created_at"][:16])
    await q.edit_message_text(txt[:4000], reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# 🎟️ SOPORTE / TICKETS
# ──────────────────────────────────────────────────────────────
async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(msg.support_menu_text(), reply_markup=kb.support_menu(), parse_mode=ParseMode.MARKDOWN)

async def ticket_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(msg.ticket_ask_subject(), reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_SUBJECT

async def ticket_subject_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ticket_subject"] = update.message.text.strip()[:100]
    await update.message.reply_text(msg.ticket_ask_message(), reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_MESSAGE

async def ticket_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user      = update.effective_user
    subject   = context.user_data.get("ticket_subject", "Sin asunto")
    content   = update.message.text.strip()
    ticket_id = await db.create_ticket(user.id, user.username or "", user.first_name, subject)
    await db.add_ticket_message(ticket_id, user.id, content, is_admin=False)
    await db.log_event("ticket", user.id, f"id={ticket_id}")
    await update.message.reply_text(msg.ticket_created(ticket_id, subject), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())

    # Notificar a todos los admins
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(
            context.bot, aid,
            f"🎟️ *Nuevo ticket #{ticket_id:04d}*\n👤 {user.first_name} (`{user.id}`)\n📌 _{subject}_\n\n{content}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_ticket_actions(ticket_id, True)
        )

    context.user_data.clear()
    return ConversationHandler.END

async def ticket_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    await q.answer()
    user    = q.from_user
    tickets = await db.get_user_tickets(user.id)
    txt     = msg.ticket_list_header()
    if not tickets:
        txt += "_No tienes tickets registrados._"
    for t in tickets:
        txt += msg.ticket_item(t["id"], t["subject"], t["status"], t["updated_at"][:16])
    buttons = [[InlineKeyboardButton(f"📬 Ver #{t['id']:04d}", callback_data=f"ticket_view_{t['id']}")] for t in tickets[:5] if t["status"] == "open"]
    buttons.append([InlineKeyboardButton("🏠 Menú principal", callback_data="main_menu")])
    await q.edit_message_text(txt[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def ticket_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
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

async def ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    context.user_data["reply_ticket_id"] = ticket_id
    await q.edit_message_text(f"💬 Responder ticket *#{ticket_id:04d}*\n\nEscribe tu mensaje:", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.cancel_keyboard())
    return STATE_TICKET_REPLY_USER

async def ticket_reply_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user      = update.effective_user
    ticket_id = context.user_data.get("reply_ticket_id")
    text      = update.message.text.strip()
    await db.add_ticket_message(ticket_id, user.id, text, is_admin=False)
    await update.message.reply_text(msg.ticket_reply_sent(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.support_menu())
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(context.bot, aid, f"💬 *Respuesta ticket #{ticket_id:04d}*\n👤 {user.first_name}: {text}", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_ticket_actions(ticket_id, True))
    context.user_data.clear()
    return ConversationHandler.END

async def ticket_close_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.close_ticket(ticket_id)
    await q.edit_message_text(msg.ticket_closed_user(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.support_menu())

async def ticket_reopen_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.reopen_ticket(ticket_id)
    await q.answer("🔄 Ticket reabierto.", show_alert=True)


# ──────────────────────────────────────────────────────────────
# ADMIN — Panel
# ──────────────────────────────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return
    stats = await db.get_stats_summary()
    await update.message.reply_text(msg.admin_panel_text(stats), reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return
    q     = update.callback_query
    await q.answer()
    stats = await db.get_stats_summary()
    await q.edit_message_text(msg.admin_panel_text(stats), reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)


# ── Generar código ──
async def adm_gen_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔑 *Generar código VIP*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Atajos rápidos abajo, o escribe:\n"
        "`DIAS USOS` → código aleatorio\n"
        "`CODIGO DIAS USOS [NOTA]` → personalizado\n"
        "`DIAS USOS NOTA exp:DD/MM/YYYY` → con expiración",
        reply_markup=kb.admin_gen_code_shortcuts(), parse_mode=ParseMode.MARKDOWN
    )
    return STATE_GEN_CODE

async def adm_gen_code_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q    = update.callback_query
    await q.answer()
    days = {"7": 7, "15": 15, "30": 30, "60": 60, "90": 90}.get(q.data.split("_")[-1], 30)
    code = await unique_code()
    admin_id = update.effective_user.id
    await db.create_code(code, days, 1, created_by=admin_id)
    await db.audit(admin_id, "gen_code", code, f"{days}d 1uso")
    await q.edit_message_text(msg.admin_code_created(code, days, 1, ""), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def adm_gen_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    admin_id = update.effective_user.id
    text     = update.message.text.strip()

    # Parsear fecha de expiración opcional: exp:DD/MM/YYYY
    expires_at = None
    if "exp:" in text.lower():
        parts_exp = text.lower().split("exp:")
        text      = parts_exp[0].strip()
        try:
            exp_date   = datetime.strptime(parts_exp[1].strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc)
            expires_at = exp_date.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            await update.message.reply_text("⚠️ Formato de fecha inválido. Usa `exp:DD/MM/YYYY`", parse_mode=ParseMode.MARKDOWN)
            return STATE_GEN_CODE

    parts = text.split()
    try:
        if len(parts) == 2:
            days, uses, code, note = int(parts[0]), int(parts[1]), await unique_code(), ""
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
        await update.message.reply_text("⚠️ Formato inválido. Ej: `30 5` o `PROMO30 30 1 Nota`", parse_mode=ParseMode.MARKDOWN)
        return STATE_GEN_CODE

    await db.create_code(code, days, uses, note, expires_at, admin_id)
    await db.audit(admin_id, "gen_code", code, f"{days}d {uses}usos")
    await update.message.reply_text(msg.admin_code_created(code, days, uses, note, expires_at), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ── Lista / Stats / Ranking ──
async def adm_list_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(msg.admin_codes_list(await db.list_codes()), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(msg.admin_members_list(await db.get_active_members()), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(msg.admin_stats(await db.get_stats_summary(), await db.get_active_members()), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(msg.admin_ranking(await db.get_ranking(10)), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Multi-admin ──
async def adm_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("👑 *Gestión de Admins*", reply_markup=kb.admin_admins_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    admins = await db.list_admins()
    await q.edit_message_text(msg.admin_admins_list(admins, ADMIN_ID), reply_markup=kb.admin_admins_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("👑 Escribe el `USER_ID` del nuevo admin:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_ADD_ADMIN

async def adm_add_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ ID inválido.", reply_markup=kb.admin_back())
        return ConversationHandler.END
    await db.add_admin(uid, "", "", admin_id)
    await db.audit(admin_id, "add_admin", str(uid))
    await update.message.reply_text(msg.admin_add_admin_success(uid), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    await notify_user(context.bot, uid, "👑 Has sido añadido como administrador del bot VIP.")
    return ConversationHandler.END

async def adm_remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("➖ Escribe el `USER_ID` del admin a remover:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_REMOVE_ADMIN

async def adm_remove_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ ID inválido.", reply_markup=kb.admin_back())
        return ConversationHandler.END
    if uid == ADMIN_ID:
        await update.message.reply_text("⚠️ No puedes remover al admin principal.", reply_markup=kb.admin_back())
        return ConversationHandler.END
    await db.remove_admin(uid)
    await db.audit(admin_id, "remove_admin", str(uid))
    await update.message.reply_text(msg.admin_remove_admin_success(uid), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

# Comandos directos de admin
async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Uso: `/addadmin USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    uid = int(context.args[0])
    await db.add_admin(uid, "", "", update.effective_user.id)
    await db.audit(update.effective_user.id, "add_admin", str(uid))
    await update.message.reply_text(msg.admin_add_admin_success(uid), parse_mode=ParseMode.MARKDOWN)

async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Uso: `/removeadmin USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    uid = int(context.args[0])
    if uid == ADMIN_ID:
        await update.message.reply_text("⚠️ No puedes remover al admin principal.")
        return
    await db.remove_admin(uid)
    await db.audit(update.effective_user.id, "remove_admin", str(uid))
    await update.message.reply_text(msg.admin_remove_admin_success(uid), parse_mode=ParseMode.MARKDOWN)


# ── Blacklist ──
async def adm_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🚫 *Gestión de Blacklist*", reply_markup=kb.admin_blacklist_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_blacklist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(msg.admin_blacklist_list(await db.get_blacklist()), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ban_input_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🚫 Escribe: `USER_ID razón`", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_BAN_INPUT

async def adm_ban_input_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts    = update.message.text.strip().split(maxsplit=1)
    admin_id = update.effective_user.id
    try:
        uid    = int(parts[0])
        reason = parts[1] if len(parts) > 1 else ""
    except ValueError:
        await update.message.reply_text("⚠️ ID inválido.", reply_markup=kb.admin_back())
        return ConversationHandler.END
    await db.ban_user(uid, reason, admin_id)
    await db.audit(admin_id, "ban", str(uid), reason)
    await kick_from_channel(context.bot, uid)
    await update.message.reply_text(msg.admin_ban_success(uid), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    await notify_user(context.bot, uid, "🚫 Tu acceso ha sido suspendido.")
    return ConversationHandler.END

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    if not context.args: return
    uid    = int(context.args[0])
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    await db.ban_user(uid, reason, update.effective_user.id)
    await db.audit(update.effective_user.id, "ban", str(uid), reason)
    await kick_from_channel(context.bot, uid)
    await update.message.reply_text(msg.admin_ban_success(uid), parse_mode=ParseMode.MARKDOWN)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    if not context.args: return
    uid = int(context.args[0])
    await db.unban_user(uid)
    await db.audit(update.effective_user.id, "unban", str(uid))
    await update.message.reply_text(msg.admin_unban_success(uid), parse_mode=ParseMode.MARKDOWN)

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    if len(context.args) < 2: return
    uid, days = int(context.args[0]), int(context.args[1])
    ok = await db.add_days_to_subscription(uid, days)
    if ok:
        sub     = await db.get_subscription(uid)
        new_exp = fmt_expiry(datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc))
        await update.message.reply_text(msg.admin_adddays_success(uid, days, new_exp), parse_mode=ParseMode.MARKDOWN)
        await db.audit(update.effective_user.id, "adddays", str(uid), f"+{days}")
        await notify_user(context.bot, uid, f"✅ Un admin añadió *+{days} días* a tu membresía.\n📅 Nuevo vencimiento: `{new_exp}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("⚠️ Usuario sin membresía activa.")


# ── Broadcast segmentado ──
async def adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("📢 *Broadcast — Elige el segmento*", reply_markup=kb.admin_broadcast_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast_segment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    segment_map = {
        "adm_bc_all":      ("all",      "Todos los miembros"),
        "adm_bc_critical": ("critical", "Vencen en 1-3 días 🔴"),
        "adm_bc_warning":  ("warning",  "Vencen en 4-7 días 🟡"),
        "adm_bc_healthy":  ("healthy",  "Más de 7 días activos 🟢"),
    }
    segment, label = segment_map.get(q.data, ("all", "Todos"))
    context.user_data["bc_segment"] = segment
    context.user_data["bc_label"]   = label
    await q.edit_message_text(
        f"📢 *Broadcast — {label}*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nEscribe el mensaje:",
        reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN
    )
    return STATE_BROADCAST_MSG

async def adm_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    label = context.user_data.get("bc_label", "Todos")
    context.user_data["bc_msg"] = text
    await update.message.reply_text(
        msg.admin_broadcast_preview(text, label),
        reply_markup=kb.confirm_action("adm_broadcast_confirm"),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q       = update.callback_query; await q.answer()
    text    = context.user_data.get("bc_msg", "")
    segment = context.user_data.get("bc_segment", "all")
    label   = context.user_data.get("bc_label", "Todos")

    if segment == "all":
        members = await db.get_active_members()
    elif segment == "critical":
        members = await db.get_members_by_days_range(1, 3)
    elif segment == "warning":
        members = await db.get_members_by_days_range(4, 7)
    else:
        members = await db.get_members_by_days_range(8, 9999)

    sent = failed = 0
    for m in members:
        try:
            await context.bot.send_message(m["user_id"], text, parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except TelegramError:
            failed += 1

    await db.log_broadcast(text, segment, sent, failed)
    await db.audit(update.effective_user.id, "broadcast", segment, f"sent={sent} failed={failed}")
    context.user_data.clear()
    await q.edit_message_text(msg.admin_broadcast_done(sent, failed, label), reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ── Admin Tickets ──
async def adm_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🎟️ *Soporte — Tickets*", reply_markup=kb.admin_tickets_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q       = update.callback_query; await q.answer()
    tickets = await db.get_open_tickets()
    buttons = [[InlineKeyboardButton(f"📬 #{t['id']:04d} — {t['subject'][:30]}", callback_data=f"adm_tview_{t['id']}")] for t in tickets[:8]]
    buttons.append([InlineKeyboardButton("« Tickets", callback_data="adm_tickets")])
    await q.edit_message_text(msg.admin_tickets_list(tickets, open_only=True), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q       = update.callback_query; await q.answer()
    tickets = await db.get_all_tickets(30)
    buttons = []
    for t in tickets[:8]:
        st = "📬" if t["status"] == "open" else "✅"
        buttons.append([InlineKeyboardButton(f"{st} #{t['id']:04d} — {t['subject'][:25]}", callback_data=f"adm_tview_{t['id']}")])
    buttons.append([InlineKeyboardButton("« Tickets", callback_data="adm_tickets")])
    await q.edit_message_text(msg.admin_tickets_list(tickets), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q         = update.callback_query; await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    ticket    = await db.get_ticket(ticket_id)
    messages_ = await db.get_ticket_messages(ticket_id)
    if not ticket:
        await q.answer("Ticket no encontrado.", show_alert=True); return
    await q.edit_message_text(msg.admin_ticket_detail(ticket, messages_), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_ticket_actions(ticket_id, ticket["status"] == "open"))

async def adm_ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q         = update.callback_query; await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    context.user_data["adm_reply_ticket"] = ticket_id
    await q.edit_message_text(f"💬 Responder ticket *#{ticket_id:04d}*\n\nEscribe tu respuesta:", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.cancel_keyboard())
    return STATE_ADM_TICKET_REPLY

async def adm_ticket_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket_id = context.user_data.get("adm_reply_ticket")
    text      = update.message.text.strip()
    admin_id  = update.effective_user.id
    await db.add_ticket_message(ticket_id, admin_id, text, is_admin=True)
    await db.audit(admin_id, "ticket_reply", str(ticket_id))
    await update.message.reply_text(msg.admin_ticket_reply_sent(ticket_id), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())
    ticket = await db.get_ticket(ticket_id)
    if ticket:
        await notify_user(context.bot, ticket["user_id"], msg.ticket_new_reply_user(ticket_id, text), parse_mode=ParseMode.MARKDOWN)
    context.user_data.clear()
    return ConversationHandler.END

async def adm_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q         = update.callback_query; await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.close_ticket(ticket_id)
    await db.audit(update.effective_user.id, "ticket_close", str(ticket_id))
    ticket    = await db.get_ticket(ticket_id)
    messages_ = await db.get_ticket_messages(ticket_id)
    await q.edit_message_text(msg.admin_ticket_detail(ticket, messages_), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_ticket_actions(ticket_id, False))

async def adm_ticket_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q         = update.callback_query; await q.answer()
    ticket_id = int(q.data.split("_")[-1])
    await db.reopen_ticket(ticket_id)
    await q.answer("🔄 Ticket reabierto.", show_alert=True)


# ── Mantenimiento ──
async def adm_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🔧 *Mantenimiento*", reply_markup=kb.admin_maintenance_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_clean_expired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("🧹 Limpiando...")
    expired = await db.get_expired_members()
    count   = 0
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        count += 1
    await db.audit(update.effective_user.id, "clean_expired", "", f"removed={count}")
    await q.edit_message_text(f"✅ *Limpieza completada*\nExpulsados: *{count}*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("📤 Generando CSV...")
    try:
        csv_data  = await db.export_members_csv()
        csv_bytes = io.BytesIO(csv_data.encode("utf-8"))
        csv_bytes.name = f"members_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        await context.bot.send_document(
            update.effective_user.id,
            document=csv_bytes,
            filename=csv_bytes.name,
            caption="📊 Exportación de miembros VIP"
        )
        await db.audit(update.effective_user.id, "export_csv", "", "")
    except Exception as e:
        logger.error(f"export_csv error: {e}")
        await q.answer("⚠️ Error al generar CSV.", show_alert=True)

async def adm_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    try:
        from database import DB_PATH
        await context.bot.send_document(
            update.effective_user.id,
            document=open(DB_PATH, "rb"),
            filename=f"vip_backup_{datetime.now().strftime('%Y%m%d')}.db"
        )
    except Exception as e:
        logger.error(f"backup error: {e}")
        await q.answer("⚠️ Error al generar backup.", show_alert=True)

async def adm_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q    = update.callback_query; await q.answer()
    logs = await db.get_audit_log(30)
    txt  = "📋 *Log de auditoría*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for l in logs:
        txt += f"`{l['created_at'][:16]}` *{l['action']}* {l['target'] or ''}\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q       = update.callback_query; await q.answer()
    history = await db.get_broadcast_history(10)
    txt     = "📜 *Historial broadcasts*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for b in history:
        txt += f"`{b['created_at'][:16]}` [{b['filter_type']}] → {b['sent_to']} ok · {b['failed']} fail\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_scan_intruders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("👻 *Scan completado*\n\n_Usa limpieza forzada para expulsar vencidos._", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# JOBS AUTOMÁTICOS
# ──────────────────────────────────────────────────────────────
async def job_clean_expired(context: ContextTypes.DEFAULT_TYPE):
    expired = await db.get_expired_members()
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        await notify_user(context.bot, m["user_id"], msg.expired_notification(), parse_mode=ParseMode.MARKDOWN)
    if expired:
        logger.info(f"job_clean_expired: removed {len(expired)} members")

async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE):
    for hours in [72, 24]:
        for m in await db.get_expiring_soon(hours):
            await notify_user(context.bot, m["user_id"], msg.expiry_warning(days_left(m["expiry"])), parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    stats     = await db.get_stats_summary()
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(context.bot, aid, msg.daily_summary(stats), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# AUTO-RESPUESTA
# ──────────────────────────────────────────────────────────────
async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return
    user = update.effective_user
    text = (update.message.text or "").lower()
    for keywords, reply in {
        ("hola", "hi", "buenas", "hey"): f"👋 ¡Hola {user.first_name}! Usa el menú para gestionar tu acceso.",
        ("precio", "costo", "plan", "cuanto"): "💎 Contacta al admin para información sobre planes VIP.",
        ("ayuda", "help", "soporte", "problema"): "🎟️ Usa el botón *Soporte* del menú para abrir un ticket.",
        ("canal", "acceso", "link", "grupo"): "🔑 Activa tu código VIP para acceder al canal exclusivo.",
        ("gracias", "thanks", "ty"): f"🙌 ¡Con gusto, {user.first_name}!",
    }.items():
        if any(k in text for k in keywords):
            await update.message.reply_text(reply, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
            return
    await update.message.reply_text(
        f"💬 ¿En qué puedo ayudarte, {user.first_name}?\nUsa el menú o abre un ticket de soporte.",
        reply_markup=kb.main_menu()
    )


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    import asyncio

    async def _run():
        await db.init_db()

        if not BOT_TOKEN:
            logger.critical("BOT_TOKEN no configurado. Saliendo.")
            return

        # Arrancar servidor HTTP API
        await start_api_server()

        app = Application.builder().token(BOT_TOKEN).build()

        # ── Conversations ──
        convs = [
            ConversationHandler(
                entry_points=[CallbackQueryHandler(activate_start, pattern="^activate$")],
                states={STATE_ACTIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
                states={STATE_RENEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_gen_code_menu, pattern="^adm_gen_code$")],
                states={STATE_GEN_CODE: [
                    CallbackQueryHandler(adm_gen_code_quick, pattern="^adm_quick_"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gen_code_input)
                ]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_ban_input_start, pattern="^adm_ban_input$")],
                states={STATE_BAN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_input_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[
                    CallbackQueryHandler(adm_broadcast_segment, pattern="^adm_bc_"),
                ],
                states={STATE_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_preview)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_new_start, pattern="^ticket_new$")],
                states={
                    STATE_TICKET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_subject_received)],
                    STATE_TICKET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_message_received)],
                },
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_reply_start, pattern="^ticket_reply_")],
                states={STATE_TICKET_REPLY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_reply_user_message)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_ticket_reply_start, pattern="^adm_ticket_reply_")],
                states={STATE_ADM_TICKET_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ticket_reply_message)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_add_admin_start, pattern="^adm_add_admin$")],
                states={STATE_ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_remove_admin_start, pattern="^adm_remove_admin$")],
                states={STATE_REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_remove_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")], conversation_timeout=300
            ),
        ]
        for conv in convs:
            app.add_handler(conv)

        # ── Comandos ──
        for cmd, fn in [
            ("start",        start_handler),
            ("admin",        admin_command),
            ("ban",          ban_command),
            ("unban",        unban_command),
            ("adddays",      adddays_command),
            ("addadmin",     addadmin_command),
            ("removeadmin",  removeadmin_command),
        ]:
            app.add_handler(CommandHandler(cmd, fn))

        # ── Callbacks ──
        callbacks = [
            ("^main_menu$",            main_menu_callback),
            ("^free_trial$",           free_trial_callback),
            ("^history$",              history_callback),
            ("^support$",              support_callback),
            ("^ticket_list$",          ticket_list_callback),
            ("^ticket_view_",          ticket_view_callback),
            ("^ticket_close_",         ticket_close_user),
            ("^ticket_reopen_",        ticket_reopen_user),
            ("^adm_panel$",            admin_panel_callback),
            ("^adm_list_codes$",       adm_list_codes),
            ("^adm_members$",          adm_members),
            ("^adm_stats$",            adm_stats),
            ("^adm_ranking$",          adm_ranking),
            ("^adm_admins$",           adm_admins),
            ("^adm_list_admins$",      adm_list_admins),
            ("^adm_blacklist$",        adm_blacklist),
            ("^adm_blacklist_list$",   adm_blacklist_list),
            ("^adm_broadcast$",        adm_broadcast),
            ("^adm_broadcast_confirm$",adm_broadcast_confirm),
            ("^adm_maintenance$",      adm_maintenance),
            ("^adm_clean_expired$",    adm_clean_expired),
            ("^adm_export_csv$",       adm_export_csv),
            ("^adm_backup$",           adm_backup),
            ("^adm_audit_log$",        adm_audit_log),
            ("^adm_broadcast_history$",adm_broadcast_history),
            ("^adm_scan_intruders$",   adm_scan_intruders),
            ("^adm_tickets$",          adm_tickets),
            ("^adm_tickets_open$",     adm_tickets_open),
            ("^adm_tickets_all$",      adm_tickets_all),
            ("^adm_tview_",            adm_ticket_view),
            ("^adm_ticket_close_",     adm_ticket_close),
            ("^adm_ticket_reopen_",    adm_ticket_reopen),
        ]
        for pattern, fn in callbacks:
            app.add_handler(CallbackQueryHandler(fn, pattern=pattern))

        # ── Auto-respuesta ──
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply))

        # ── Jobs ──
        jq: JobQueue = app.job_queue
        jq.run_repeating(job_clean_expired, interval=3600,  first=60)
        jq.run_repeating(job_warn_expiring, interval=43200, first=120)
        jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time())

        logger.info(f"🚀 VIP Bot iniciado | Canal: {CHANNEL_ID} | Admin: {ADMIN_ID}")

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Mantener vivo
        import signal
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()

        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
