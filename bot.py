"""
bot.py — VIP Bot · Versión mejorada
Mejoras añadidas:
  ✅ /api/news    — Endpoint con caché de noticias ForexLive (10 min)
  ✅ /api/calendar — Endpoint con calendario económico de la semana
  ✅ job_news_alerts    — Alertas de eventos de ALTO impacto 30 min antes
  ✅ job_warn_expiring  — Mejorado: avisa a 72h, 24h y 1h antes del vencimiento
  ✅ CORS mejorado para Mini App
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
import asyncio
import aiohttp
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

BOT_TOKEN       = os.getenv("BOT_TOKEN")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID      = int(os.getenv("CHANNEL_ID", "-1003738953503"))
FREE_TRIAL_DAYS = 30
API_PORT        = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))

# ──────────────────────────────────────────────────────────────
# CACHÉ EN MEMORIA (sin Redis ni DB extra)
# ──────────────────────────────────────────────────────────────
_news_cache: dict = {"items": [], "fetched_at": None}
_calendar_cache: dict = {"events": [], "fetched_at": None}
_alerted_events: set = set()   # IDs de eventos ya alertados para no repetir

NEWS_CACHE_SECONDS     = 600   # 10 minutos
CALENDAR_CACHE_SECONDS = 1800  # 30 minutos

# ──────────────────────────────────────────────────────────────
# CORS HEADERS
# ──────────────────────────────────────────────────────────────
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


# ──────────────────────────────────────────────────────────────
# TELEGRAM initData VERIFICACIÓN
# ──────────────────────────────────────────────────────────────
def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
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


# ──────────────────────────────────────────────────────────────
# API ENDPOINT — /api/user_info  (sin cambios)
# ──────────────────────────────────────────────────────────────
async def api_user_info(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    init_data = request.rel_url.query.get("initData", "")
    user = None
    uid  = 0

    if init_data:
        user = verify_telegram_init_data(init_data, BOT_TOKEN or "")
        if user:
            uid = user.get("id", 0)
        if uid == 0:
            try:
                params   = dict(parse_qsl(init_data, keep_blank_values=True))
                user_raw = json.loads(unquote(params.get("user", "{}")))
                uid      = user_raw.get("id", 0)
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
        return web.json_response({"error": "missing user_id"}, status=400, headers=CORS)

    sub = await db.get_subscription(uid)
    if not sub:
        return web.json_response({
            "has_membership": False,
            "user_id": uid,
            "first_name": user.get("first_name", "") if user else "",
        }, headers=CORS)

    expiry_dt   = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    now_dt      = datetime.now(timezone.utc)
    seconds_left = max(0, int((expiry_dt - now_dt).total_seconds()))

    return web.json_response({
        "has_membership":  True,
        "user_id":         uid,
        "first_name":      sub["first_name"] or (user.get("first_name", "") if user else ""),
        "username":        sub["username"] or "",
        "expiry":          sub["expiry"],
        "expires_at_ts":   int(expiry_dt.timestamp() * 1000),
        "seconds_left":    seconds_left,
        "total_days":      sub["total_days"] or 0,
        "is_expired":      now_dt > expiry_dt,
    }, headers=CORS)


# ──────────────────────────────────────────────────────────────
# API ENDPOINT — /api/news  ← NUEVO
# Devuelve noticias de ForexLive con caché de 10 minutos
# ──────────────────────────────────────────────────────────────
async def api_news(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    now = datetime.now(timezone.utc).timestamp()
    cached = _news_cache

    # Devolver caché si es reciente
    if cached["fetched_at"] and (now - cached["fetched_at"]) < NEWS_CACHE_SECONDS:
        return web.json_response({
            "items":      cached["items"],
            "cached":     True,
            "fetched_at": cached["fetched_at"],
            "age_seconds": int(now - cached["fetched_at"]),
        }, headers=CORS)

    # Fetch fresco desde RSS
    try:
        rss_url = "https://api.rss2json.com/v1/api.json?rss_url=https%3A%2F%2Fwww.forexlive.com%2Ffeed%2Fnews&count=15"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(rss_url) as resp:
                data = await resp.json(content_type=None)

        if data.get("status") != "ok" or not data.get("items"):
            raise ValueError("RSS sin datos")

        items = [
            {
                "title":   item.get("title", ""),
                "link":    item.get("link", ""),
                "pubDate": item.get("pubDate", ""),
                "source":  "ForexLive",
            }
            for item in data["items"][:15]
        ]

        _news_cache["items"]      = items
        _news_cache["fetched_at"] = now
        logger.info(f"api_news: actualizadas {len(items)} noticias")

        return web.json_response({
            "items":      items,
            "cached":     False,
            "fetched_at": now,
            "age_seconds": 0,
        }, headers=CORS)

    except Exception as e:
        logger.warning(f"api_news fetch error: {e}")
        # Si falla, devolver caché vieja si existe
        if cached["items"]:
            return web.json_response({
                "items":   cached["items"],
                "cached":  True,
                "error":   "fetch_failed_using_cache",
            }, headers=CORS)
        return web.json_response({"error": "no_data", "items": []}, status=503, headers=CORS)


# ──────────────────────────────────────────────────────────────
# API ENDPOINT — /api/calendar  ← NUEVO
# Devuelve el calendario económico de la semana con caché 30 min
# ──────────────────────────────────────────────────────────────
async def api_calendar(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    now    = datetime.now(timezone.utc).timestamp()
    cached = _calendar_cache

    if cached["fetched_at"] and (now - cached["fetched_at"]) < CALENDAR_CACHE_SECONDS:
        return web.json_response({
            "events":     cached["events"],
            "cached":     True,
            "age_seconds": int(now - cached["fetched_at"]),
        }, headers=CORS)

    try:
        cal_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(cal_url) as resp:
                events = await resp.json(content_type=None)

        _calendar_cache["events"]     = events
        _calendar_cache["fetched_at"] = now
        logger.info(f"api_calendar: {len(events)} eventos cargados")

        return web.json_response({
            "events":     events,
            "cached":     False,
            "age_seconds": 0,
        }, headers=CORS)

    except Exception as e:
        logger.warning(f"api_calendar fetch error: {e}")
        if cached["events"]:
            return web.json_response({"events": cached["events"], "cached": True, "error": "fetch_failed_using_cache"}, headers=CORS)
        return web.json_response({"error": "no_data", "events": []}, status=503, headers=CORS)


# ──────────────────────────────────────────────────────────────
# HTTP SERVER
# ──────────────────────────────────────────────────────────────
async def start_api_server():
    app_http = web.Application()
    # Rutas existentes
    app_http.router.add_route("GET",     "/api/user_info", api_user_info)
    app_http.router.add_route("OPTIONS", "/api/user_info", api_user_info)
    # Rutas nuevas
    app_http.router.add_route("GET",     "/api/news",      api_news)
    app_http.router.add_route("OPTIONS", "/api/news",      api_news)
    app_http.router.add_route("GET",     "/api/calendar",  api_calendar)
    app_http.router.add_route("OPTIONS", "/api/calendar",  api_calendar)

    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    logger.info(f"🌐 API HTTP corriendo en :{API_PORT}  (news + calendar endpoints activos)")


# ──────────────────────────────────────────────────────────────
# Estados de conversación
# ──────────────────────────────────────────────────────────────
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
# PRUEBA GRATIS
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
# SOPORTE / TICKETS  (sin cambios)
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
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(
            context.bot, aid,
            f"🎟️ *Nuevo ticket #{ticket_id:04d}*\n👤 {user.first_name} (`{user.id}`)\n📌 _{subject}_\n\n{content}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_ticket_actions(ticket_id, True)
        )
    return ConversationHandler.END

async def ticket_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return
    q = update.callback_query; await q.answer()
    tickets = await db.get_user_tickets(q.from_user.id)
    if not tickets:
        await q.edit_message_text("📭 No tienes tickets abiertos.", reply_markup=kb.main_menu())
        return
    txt = "🎟️ *Tus tickets*\n━━━━━━━━━━━━━━━━\n\n"
    btns = []
    for t in tickets[:10]:
        st = "🟢" if t["status"] == "open" else "⚫"
        txt += f"{st} *#{t['id']:04d}* — {t['subject'][:40]}\n"
        btns.append([InlineKeyboardButton(f"#{t['id']:04d} {t['subject'][:25]}", callback_data=f"ticket_view_{t['id']}")])
    btns.append([InlineKeyboardButton("← Menú", callback_data="main_menu")])
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def ticket_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    ticket = await db.get_ticket(tid)
    if not ticket or ticket["user_id"] != q.from_user.id:
        await q.answer("❌ Ticket no encontrado.", show_alert=True); return
    messages_list = await db.get_ticket_messages(tid)
    txt = f"🎟️ *Ticket #{tid:04d}*\n📌 _{ticket['subject']}_\n🔘 Estado: {'🟢 Abierto' if ticket['status'] == 'open' else '⚫ Cerrado'}\n━━━━━━━━━━━━━━━━\n\n"
    for m in messages_list[-5:]:
        who = "👤" if not m["is_admin"] else "🛡️ Admin"
        txt += f"*{who}* `{m['sent_at'][:16]}`\n{m['message'][:200]}\n\n"
    btns = []
    if ticket["status"] == "open":
        btns.append([InlineKeyboardButton("↩️ Responder", callback_data=f"ticket_reply_{tid}")])
        btns.append([InlineKeyboardButton("✅ Cerrar ticket", callback_data=f"ticket_close_{tid}")])
    else:
        btns.append([InlineKeyboardButton("🔄 Reabrir", callback_data=f"ticket_reopen_{tid}")])
    btns.append([InlineKeyboardButton("← Mis tickets", callback_data="ticket_list")])
    await q.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    context.user_data["reply_ticket_id"] = tid
    await q.edit_message_text(f"✍️ Escribe tu respuesta para el ticket *#{tid:04d}*:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_REPLY_USER

async def ticket_reply_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tid  = context.user_data.get("reply_ticket_id")
    if not tid:
        return ConversationHandler.END
    await db.add_ticket_message(tid, user.id, update.message.text.strip(), is_admin=False)
    await update.message.reply_text(f"✅ Respuesta enviada al ticket *#{tid:04d}*.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(
            context.bot, aid,
            f"🔔 *Respuesta en ticket #{tid:04d}*\n👤 {user.first_name}\n\n{update.message.text.strip()[:300]}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb.admin_ticket_actions(tid, True)
        )
    return ConversationHandler.END

async def ticket_close_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)
    await q.edit_message_text(f"✅ Ticket *#{tid:04d}* cerrado.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())

async def ticket_reopen_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)
    await q.edit_message_text(f"🔄 Ticket *#{tid:04d}* reabierto.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())

# Admin ticket handlers (preservados del original)
async def adm_tickets(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    open_c = len(await db.get_open_tickets())
    await q.edit_message_text(
        f"🎟️ *Gestión de Tickets*\n━━━━━━━━━━━━━━━━\n\n📂 Tickets abiertos: *{open_c}*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 Ver abiertos", callback_data="adm_tickets_open")],
            [InlineKeyboardButton("📋 Ver todos", callback_data="adm_tickets_all")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_tickets_open(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    tickets = await db.get_open_tickets()
    if not tickets:
        await q.edit_message_text("✅ Sin tickets abiertos.", reply_markup=kb.admin_back()); return
    btns = [[InlineKeyboardButton(f"#{t['id']:04d} {t['subject'][:28]}", callback_data=f"adm_tview_{t['id']}")] for t in tickets[:10]]
    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])
    await q.edit_message_text("🟢 *Tickets abiertos*", reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_all(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    tickets = await db.get_all_tickets(20)
    btns = [[InlineKeyboardButton(f"{'🟢' if t['status']=='open' else '⚫'} #{t['id']:04d} {t['subject'][:25]}", callback_data=f"adm_tview_{t['id']}")] for t in tickets]
    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])
    await q.edit_message_text("📋 *Todos los tickets*", reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_view(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    ticket = await db.get_ticket(tid)
    if not ticket:
        await q.answer("Ticket no encontrado", show_alert=True); return
    msgs = await db.get_ticket_messages(tid)
    txt  = f"🎟️ *#{tid:04d}* — {ticket['subject']}\n👤 {ticket['first_name']} | {ticket['status']}\n━━━━━━━━━━━━━━━━\n\n"
    for m in msgs[-6:]:
        who = "🛡️" if m["is_admin"] else "👤"
        txt += f"{who} `{m['sent_at'][:16]}`\n{m['message'][:200]}\n\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_ticket_actions(tid, ticket["status"]=="open"), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_reply_start(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    context.user_data["adm_reply_ticket"] = tid
    await q.edit_message_text(f"✍️ Responde al ticket *#{tid:04d}*:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_ADM_TICKET_REPLY

async def adm_ticket_reply_message(update, context):
    admin  = update.effective_user
    tid    = context.user_data.get("adm_reply_ticket")
    if not tid: return ConversationHandler.END
    ticket = await db.get_ticket(tid)
    await db.add_ticket_message(tid, admin.id, update.message.text.strip(), is_admin=True)
    await update.message.reply_text(f"✅ Respuesta enviada al ticket *#{tid:04d}*.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())
    if ticket:
        await notify_user(context.bot, ticket["user_id"],
            f"🔔 *Respuesta de soporte en ticket #{tid:04d}*\n\n{update.message.text.strip()[:500]}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb.main_menu())
    return ConversationHandler.END

async def adm_ticket_close(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)
    await q.edit_message_text(f"✅ Ticket *#{tid:04d}* cerrado.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())

async def adm_ticket_reopen(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)
    await q.edit_message_text(f"🔄 Ticket *#{tid:04d}* reabierto.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())


# ──────────────────────────────────────────────────────────────
# ADMIN PANEL (preservado del original — funciones clave)
# ──────────────────────────────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Sin permisos.")
        return
    await update.message.reply_text("🛡️ *Panel de Admin*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🛡️ *Panel de Admin*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)

async def adm_gen_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "🔑 *Generar código VIP*\n━━━━━━━━━━━━━━━━\n\nElige duración:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("7 días",  callback_data="adm_quick_7"),
             InlineKeyboardButton("30 días", callback_data="adm_quick_30")],
            [InlineKeyboardButton("90 días", callback_data="adm_quick_90"),
             InlineKeyboardButton("365 días",callback_data="adm_quick_365")],
            [InlineKeyboardButton("Personalizado", callback_data="adm_quick_custom")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_GEN_CODE

async def adm_gen_code_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q    = update.callback_query; await q.answer()
    data = q.data.split("_")[-1]
    if data == "custom":
        await q.edit_message_text("✏️ Escribe: `días usos [nota]`\nEjemplo: `30 1 Cliente premium`", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.cancel_keyboard())
        return STATE_GEN_CODE
    days = int(data)
    code = await unique_code()
    await db.create_code(code, days, 1, created_by=q.from_user.id)
    await db.audit(q.from_user.id, "gen_code", code, f"days={days}")
    await q.edit_message_text(
        f"✅ *Código generado*\n━━━━━━━━━━━━━━━━\n\n`{code}`\n\n📅 Días: *{days}*\n🔂 Usos: *1*",
        reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_gen_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    parts = update.message.text.strip().split()
    try:
        days  = int(parts[0])
        uses  = int(parts[1]) if len(parts) > 1 else 1
        note  = " ".join(parts[2:]) if len(parts) > 2 else ""
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Formato: `días usos [nota]`", parse_mode=ParseMode.MARKDOWN)
        return STATE_GEN_CODE
    code = await unique_code()
    await db.create_code(code, days, uses, note, created_by=update.effective_user.id)
    await db.audit(update.effective_user.id, "gen_code", code, f"days={days} uses={uses}")
    await update.message.reply_text(
        f"✅ *Código generado*\n\n`{code}`\n\n📅 Días: *{days}* | 🔂 Usos: *{uses}*{f' | 📝 {note}' if note else ''}",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back()
    )
    return ConversationHandler.END

async def adm_list_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    codes = await db.get_active_codes()
    if not codes:
        await q.edit_message_text("📭 Sin códigos activos.", reply_markup=kb.admin_back()); return
    txt = "🔑 *Códigos activos*\n━━━━━━━━━━━━━━━━\n\n"
    for c in codes[:20]:
        rem = f"{c['max_uses']-c['used_count']}/{c['max_uses']}"
        txt += f"`{c['code']}` — {c['days']}d — {rem} usos\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    members = await db.get_all_subscriptions()
    if not members:
        await q.edit_message_text("📭 Sin miembros.", reply_markup=kb.admin_back()); return
    txt = f"👥 *Miembros activos ({len(members)})*\n━━━━━━━━━━━━━━━━\n\n"
    for m in members[:20]:
        d = days_left(m["expiry"])
        txt += f"• {m['first_name']} (`{m['user_id']}`) — {d}d restantes\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    s = await db.get_stats_summary()
    txt = (f"📊 *Estadísticas*\n━━━━━━━━━━━━━━━━\n\n"
           f"👥 Total miembros: *{s['total']}*\n✅ Activos: *{s['active']}*\n"
           f"🆕 Nuevos hoy: *{s['new_today']}*\n⚠️ Vencen en 3d: *{s['expiring_3d']}*\n"
           f"🔑 Códigos activos: *{s['codes']}*\n🎟️ Tickets abiertos: *{s['tickets_open']}*\n"
           f"🚫 Bloqueados: *{s['banned']}*\n🆓 Pruebas usadas: *{s['trials']}*")
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    rank = await db.get_ranking(10)
    txt  = "🏆 *Ranking VIP*\n━━━━━━━━━━━━━━━━\n\n"
    medals = ["🥇","🥈","🥉"] + ["🏅"]*7
    for i, m in enumerate(rank):
        txt += f"{medals[i]} {m['first_name']} — *{m['total_days']}d* acumulados\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "📢 *Broadcast*\n\n¿A quién enviar?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Todos",         callback_data="adm_bc_all")],
            [InlineKeyboardButton("✅ Solo activos",  callback_data="adm_bc_active")],
            [InlineKeyboardButton("⚠️ Por vencer 3d", callback_data="adm_bc_expiring")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_broadcast_segment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    seg = q.data.replace("adm_bc_", "")
    BROADCAST_FILTER["segment"] = seg
    await q.edit_message_text(f"✍️ Escribe el mensaje a enviar ({seg}):", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_BROADCAST_MSG

async def adm_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seg = BROADCAST_FILTER.get("segment", "all")
    context.user_data["bc_message"] = update.message.text.strip()
    await update.message.reply_text(
        f"📢 *Preview broadcast ({seg})*\n━━━━━━━━\n\n{context.user_data['bc_message']}\n\n━━━━━━━━\n¿Confirmar?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enviar",   callback_data="adm_broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q   = update.callback_query; await q.answer("Enviando...")
    seg = BROADCAST_FILTER.get("segment", "all")
    txt = context.user_data.get("bc_message", "")
    if not txt:
        await q.edit_message_text("❌ Sin mensaje.", reply_markup=kb.admin_back()); return
    if seg == "active":
        members = [m for m in await db.get_all_subscriptions() if days_left(m["expiry"]) > 0]
    elif seg == "expiring":
        members = await db.get_expiring_soon(72)
    else:
        members = await db.get_all_subscriptions()
    ok, fail = 0, 0
    for m in members:
        try:
            await context.bot.send_message(m["user_id"], txt, parse_mode=ParseMode.MARKDOWN)
            ok += 1
        except TelegramError:
            fail += 1
    await db.log_broadcast(txt, seg, ok, fail)
    await q.edit_message_text(f"📢 *Broadcast enviado*\n✅ {ok} ok | ❌ {fail} fallidos", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_admins(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🛡️ *Gestión de admins*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Agregar admin",  callback_data="adm_add_admin")],
            [InlineKeyboardButton("➖ Remover admin",  callback_data="adm_remove_admin")],
            [InlineKeyboardButton("📋 Listar admins",  callback_data="adm_list_admins")],
            [InlineKeyboardButton("← Admin",           callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_list_admins(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    admins = await db.list_admins()
    txt = "🛡️ *Admins activos*\n━━━━━━━━━━━━━━━━\n\n"
    txt += f"⭐ Admin principal: `{ADMIN_ID}`\n\n"
    for a in admins:
        txt += f"• {a['first_name']} (`{a['user_id']}`)\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_add_admin_start(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✏️ Escribe el user_id del nuevo admin:", reply_markup=kb.cancel_keyboard())
    return STATE_ADD_ADMIN

async def adm_add_admin_received(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        new_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID inválido."); return STATE_ADD_ADMIN
    await db.add_admin(new_id, "", "", update.effective_user.id)
    await db.audit(update.effective_user.id, "add_admin", str(new_id))
    await update.message.reply_text(f"✅ Admin `{new_id}` agregado.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())
    return ConversationHandler.END

async def adm_remove_admin_start(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✏️ Escribe el user_id a remover:", reply_markup=kb.cancel_keyboard())
    return STATE_REMOVE_ADMIN

async def adm_remove_admin_received(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        rem_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID inválido."); return STATE_REMOVE_ADMIN
    await db.remove_admin(rem_id)
    await db.audit(update.effective_user.id, "remove_admin", str(rem_id))
    await update.message.reply_text(f"✅ Admin `{rem_id}` removido.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())
    return ConversationHandler.END

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /ban <user_id> [razón]"); return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido."); return
    reason = " ".join(args[1:]) or "Sin razón"
    await db.ban_user(uid, reason, update.effective_user.id)
    await kick_from_channel(context.bot, uid)
    await update.message.reply_text(f"🚫 Usuario `{uid}` baneado.", parse_mode=ParseMode.MARKDOWN)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /unban <user_id>"); return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido."); return
    await db.unban_user(uid)
    await update.message.reply_text(f"✅ Usuario `{uid}` desbaneado.", parse_mode=ParseMode.MARKDOWN)

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /adddays <user_id> <días>"); return
    try:
        uid  = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Valores inválidos."); return
    sub = await db.get_subscription(uid)
    if not sub:
        await update.message.reply_text(f"❌ Usuario `{uid}` sin membresía.", parse_mode=ParseMode.MARKDOWN); return
    curr_exp = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    new_exp  = max(curr_exp, utc_now()) + timedelta(days=days)
    await db.upsert_subscription(uid, sub["username"], sub["first_name"], new_exp.strftime("%Y-%m-%d %H:%M:%S"), days, "MANUAL")
    await db.audit(update.effective_user.id, "adddays", str(uid), f"+{days}d")
    await update.message.reply_text(f"✅ +{days} días a `{uid}`. Nuevo vencimiento: {fmt_expiry(new_exp)}", parse_mode=ParseMode.MARKDOWN)

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /addadmin <user_id>"); return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido."); return
    await db.add_admin(uid, "", "", update.effective_user.id)
    await update.message.reply_text(f"✅ Admin `{uid}` agregado.", parse_mode=ParseMode.MARKDOWN)

async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /removeadmin <user_id>"); return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido."); return
    await db.remove_admin(uid)
    await update.message.reply_text(f"✅ Admin `{uid}` removido.", parse_mode=ParseMode.MARKDOWN)

async def adm_ban_input_start(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✏️ Escribe el user_id a banear:", reply_markup=kb.cancel_keyboard())
    return STATE_BAN_INPUT

async def adm_ban_input_received(update, context):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID inválido."); return STATE_BAN_INPUT
    await db.ban_user(uid, "Ban desde panel", update.effective_user.id)
    await kick_from_channel(context.bot, uid)
    await db.audit(update.effective_user.id, "ban", str(uid))
    await update.message.reply_text(f"🚫 Usuario `{uid}` baneado.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb.admin_back())
    return ConversationHandler.END

async def adm_blacklist(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🚫 *Lista negra*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Banear usuario", callback_data="adm_ban_input")],
            [InlineKeyboardButton("📋 Ver lista",      callback_data="adm_blacklist_list")],
            [InlineKeyboardButton("← Admin",           callback_data="adm_panel")],
        ]), parse_mode=ParseMode.MARKDOWN)

async def adm_blacklist_list(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    bl = await db.get_blacklist()
    if not bl:
        await q.edit_message_text("✅ Lista negra vacía.", reply_markup=kb.admin_back()); return
    txt = "🚫 *Lista negra*\n━━━━━━━━━━━━━━━━\n\n"
    for b in bl[:20]:
        txt += f"• `{b['user_id']}` — {b['reason'] or 'sin razón'}\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_maintenance(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("Modo mantenimiento no implementado aún.")

async def adm_clean_expired(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("Limpiando...")
    expired = await db.get_expired_members()
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        await notify_user(context.bot, m["user_id"], msg.expired_notification(), parse_mode=ParseMode.MARKDOWN)
    await q.edit_message_text(f"✅ Limpieza completada. {len(expired)} miembros eliminados.", reply_markup=kb.admin_back())

async def adm_export_csv(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("Generando CSV...")
    members = await db.get_all_subscriptions()
    output  = io.StringIO()
    writer  = __import__("csv").writer(output)
    writer.writerow(["user_id","first_name","username","expiry","total_days","renewals"])
    for m in members:
        writer.writerow([m["user_id"],m["first_name"],m["username"],m["expiry"],m["total_days"],m["renewals"]])
    output.seek(0)
    await context.bot.send_document(
        q.from_user.id,
        document=io.BytesIO(output.getvalue().encode()),
        filename=f"members_{datetime.now().strftime('%Y%m%d')}.csv",
        caption="📊 Exportación de miembros"
    )
    await q.edit_message_text("✅ CSV enviado.", reply_markup=kb.admin_back())

async def adm_backup(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer("Generando backup...")
    try:
        with open("vip_bot.db", "rb") as f:
            await context.bot.send_document(q.from_user.id, document=f, filename="vip_bot_backup.db", caption="🗄️ Backup DB")
        await q.edit_message_text("✅ Backup enviado.", reply_markup=kb.admin_back())
    except Exception as e:
        await q.answer(f"⚠️ Error: {e}", show_alert=True)

async def adm_audit_log(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    logs = await db.get_audit_log(30)
    txt  = "📋 *Log de auditoría*\n━━━━━━━━━━━━━━━━\n\n"
    for l in logs:
        txt += f"`{l['created_at'][:16]}` *{l['action']}* {l['target'] or ''}\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast_history(update, context):
    if not await is_admin(update.effective_user.id): return
    q       = update.callback_query; await q.answer()
    history = await db.get_broadcast_history(10)
    txt     = "📜 *Historial broadcasts*\n━━━━━━━━━━━━━━━━\n\n"
    for b in history:
        txt += f"`{b['created_at'][:16]}` [{b['filter_type']}] → {b['sent_to']} ok · {b['failed']} fail\n"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_scan_intruders(update, context):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query; await q.answer()
    await q.edit_message_text("👻 *Scan completado*\n\n_Usa limpieza forzada para expulsar vencidos._", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────
# JOBS AUTOMÁTICOS
# ──────────────────────────────────────────────────────────────

async def job_clean_expired(context: ContextTypes.DEFAULT_TYPE):
    """Cada hora: expulsa y elimina miembros vencidos."""
    expired = await db.get_expired_members()
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        await notify_user(context.bot, m["user_id"], msg.expired_notification(), parse_mode=ParseMode.MARKDOWN)
    if expired:
        logger.info(f"job_clean_expired: {len(expired)} miembros eliminados")


async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE):
    """
    Cada 12 horas: envía recordatorios escalonados.
    ✅ MEJORADO: avisa a 72h, 24h Y 1h antes.
    """
    IMPACT_MAP = {
        72: ("⚠️", "3 días"),
        24: ("🔔", "24 horas"),
        1:  ("🚨", "1 hora"),
    }
    for hours, (icon, label) in IMPACT_MAP.items():
        members = await db.get_expiring_soon(hours)
        for m in members:
            d_left = days_left(m["expiry"])
            text = (
                f"{icon} *¡Tu membresía VIP vence en {label}!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📅 Vencimiento: `{m['expiry'][:16]}`\n"
                f"⏳ Días restantes: *{d_left}*\n\n"
                f"{'💡 Renueva ahora para no perder acceso al canal.' if hours > 1 else '🚨 *Última oportunidad antes de perder acceso.*'}\n\n"
                f"Usa el botón *Renovar* en el menú del bot."
            )
            await notify_user(
                context.bot, m["user_id"], text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb.main_menu()
            )


async def job_calendar_alerts(context: ContextTypes.DEFAULT_TYPE):
    """
    ← NUEVO — Cada 15 minutos
    Revisa el calendario económico y avisa a TODOS los miembros activos
    sobre eventos de ALTO impacto que ocurren en los próximos 30 minutos.
    """
    global _alerted_events

    # Refrescar caché del calendario si es necesario
    now_ts = datetime.now(timezone.utc).timestamp()
    if not _calendar_cache["fetched_at"] or (now_ts - _calendar_cache["fetched_at"]) > CALENDAR_CACHE_SECONDS:
        try:
            cal_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(cal_url) as resp:
                    events = await resp.json(content_type=None)
            _calendar_cache["events"]     = events
            _calendar_cache["fetched_at"] = now_ts
        except Exception as e:
            logger.warning(f"job_calendar_alerts fetch error: {e}")
            return

    now       = datetime.now(timezone.utc)
    alert_window_start = now
    alert_window_end   = now + timedelta(minutes=35)

    # Filtrar eventos de alto impacto en la ventana de 35 minutos
    upcoming = []
    for ev in _calendar_cache.get("events", []):
        if ev.get("impact", "").lower() != "high":
            continue
        try:
            ev_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        if alert_window_start <= ev_dt <= alert_window_end:
            ev_id = f"{ev.get('title','')}_{ev_dt.strftime('%Y%m%d%H%M')}"
            if ev_id not in _alerted_events:
                upcoming.append((ev, ev_dt, ev_id))

    if not upcoming:
        return

    # Obtener todos los miembros activos
    members = await db.get_all_subscriptions()
    active  = [m for m in members if days_left(m["expiry"]) > 0]

    if not active:
        return

    # Construir el mensaje de alerta
    FLAG = {
        "USD":"🇺🇸","EUR":"🇪🇺","GBP":"🇬🇧","JPY":"🇯🇵","CAD":"🇨🇦",
        "AUD":"🇦🇺","NZD":"🇳🇿","CHF":"🇨🇭","CNY":"🇨🇳","All":"🌐",
    }

    for ev, ev_dt, ev_id in upcoming:
        mins_away = int((ev_dt - now).total_seconds() / 60)
        flag      = FLAG.get(ev.get("country",""), "🌐")
        alert_txt = (
            f"🔴 *ALERTA — Evento de Alto Impacto*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 *{ev.get('title', 'Evento')}*\n"
            f"{flag} {ev.get('country', '')}  |  "
            f"🕐 {ev_dt.strftime('%H:%M')} UTC\n"
            f"⏱ En *{mins_away} minutos*\n\n"
            f"⚡ Prepara tu gestión de riesgo.\n"
            f"🛑 Considera cerrar posiciones abiertas si el SL está cerca."
        )

        # Enviar a todos los miembros activos
        sent = 0
        for m in active:
            try:
                await context.bot.send_message(m["user_id"], alert_txt, parse_mode=ParseMode.MARKDOWN)
                sent += 1
            except TelegramError:
                pass

        # Marcar como alertado
        _alerted_events.add(ev_id)
        logger.info(f"job_calendar_alerts: '{ev.get('title')}' → {sent} usuarios notificados")

    # Limpiar alertas viejas (>24h) para no acumular memoria
    now_str = now.strftime("%Y%m%d")
    _alerted_events = {eid for eid in _alerted_events if now_str in eid or (now - timedelta(hours=24)).strftime("%Y%m%d") in eid}


async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    """Resumen diario a las 08:00 UTC para los admins."""
    stats     = await db.get_stats_summary()
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(context.bot, aid, msg.daily_summary(stats), parse_mode=ParseMode.MARKDOWN)


async def job_crypto_news(context: ContextTypes.DEFAULT_TYPE):
    """
    Cada 30 minutos: publica las últimas noticias crypto/forex
    en el canal VIP. Evita repetir noticias ya publicadas.
    """
    now_ts = datetime.now(timezone.utc).timestamp()

    # Refrescar caché si es necesario
    if not _news_cache["fetched_at"] or (now_ts - _news_cache["fetched_at"]) > NEWS_CACHE_SECONDS:
        try:
            feeds = [
                "https://api.rss2json.com/v1/api.json?rss_url=https%3A%2F%2Fes.cointelegraph.com%2Frss&count=5",
                "https://api.rss2json.com/v1/api.json?rss_url=https%3A%2F%2Fcointelegraph.com%2Frss&count=5",
                "https://api.rss2json.com/v1/api.json?rss_url=https%3A%2F%2Fcryptonoticias.com%2Ffeed%2F&count=5",
            ]
            items = []
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                for url in feeds:
                    try:
                        async with session.get(url) as resp:
                            data = await resp.json(content_type=None)
                        if data.get("status") == "ok":
                            for item in data.get("items", []):
                                items.append({
                                    "title":   item.get("title", ""),
                                    "link":    item.get("link", ""),
                                    "pubDate": item.get("pubDate", ""),
                                    "source":  data.get("feed", {}).get("title", "Crypto News"),
                                })
                    except Exception as e:
                        logger.warning(f"job_crypto_news feed error: {e}")
                        continue

            _news_cache["items"]      = items
            _news_cache["fetched_at"] = now_ts
            logger.info(f"job_crypto_news: {len(items)} noticias cargadas")
        except Exception as e:
            logger.warning(f"job_crypto_news fetch error: {e}")
            return

    # Publicar solo noticias nuevas (link no visto antes)
    published = 0
    for item in _news_cache.get("items", [])[:10]:
        link = item.get("link", "")
        if not link or link in _alerted_events:
            continue

        _alerted_events.add(link)
        text = (
            f"📰 *{item['title']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 {link}\n"
            f"📡 _{item['source']}_"
        )
        try:
            await context.bot.send_message(
                CHANNEL_ID, text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
            published += 1
            await asyncio.sleep(2)  # evitar flood de mensajes
        except TelegramError as e:
            logger.warning(f"job_crypto_news send error: {e}")

    if published:
        logger.info(f"job_crypto_news: {published} noticias publicadas en canal {CHANNEL_ID}")


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
    async def _run():
        await db.init_db()

        if not BOT_TOKEN:
            logger.critical("BOT_TOKEN no configurado. Saliendo.")
            return

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
                entry_points=[CallbackQueryHandler(adm_broadcast_segment, pattern="^adm_bc_")],
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
            ("start",       start_handler),
            ("admin",       admin_command),
            ("ban",         ban_command),
            ("unban",       unban_command),
            ("adddays",     adddays_command),
            ("addadmin",    addadmin_command),
            ("removeadmin", removeadmin_command),
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
        jq.run_repeating(job_clean_expired,    interval=3600,  first=60)
        jq.run_repeating(job_warn_expiring,    interval=43200, first=120)
        jq.run_repeating(job_calendar_alerts,  interval=900,   first=30)   # cada 15 min
        jq.run_repeating(job_crypto_news,      interval=1800,  first=90)   # ← NUEVO: noticias crypto cada 30 min
        jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time())

        logger.info(f"🚀 VIP Bot iniciado | Canal: {CHANNEL_ID} | Admin: {ADMIN_ID}")
        logger.info("📰 /api/news activo  |  📅 /api/calendar activo  |  ⏰ Alertas económicas activas")

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

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
