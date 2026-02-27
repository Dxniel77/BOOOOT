"""
bot.py — VIP Bot · VERSIÓN FULL DEFINITIVA
Flujo AMIGABLE:
  ✅ /start saluda por NOMBRE y pide código
  ✅ Usuario pega código → verifica → agrega al canal automáticamente
  ✅ Jobs automáticos: expulsar vencidos cada hora
  ✅ API endpoints para Mini App
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
import xml.etree.ElementTree as ET
import aiohttp
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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
# CONFIGURACIÓN - TUS VARIABLES
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
# CACHÉ EN MEMORIA
# ──────────────────────────────────────────────────────────────
_news_cache: dict = {"items": [], "fetched_at": None}
_calendar_cache: dict = {"events": [], "fetched_at": None}
_alerted_events: set = set()
_seen_news_links: set = set()

NEWS_CACHE_SECONDS     = 600    # 10 minutos
CALENDAR_CACHE_SECONDS = 1800   # 30 minutos

# ──────────────────────────────────────────────────────────────
# FUENTES RSS
# ──────────────────────────────────────────────────────────────
RSS_SOURCES = [
    ("🇪🇸 Cointelegraph ES",  "https://es.cointelegraph.com/rss",                    "es"),
    ("🇪🇸 BeInCrypto ES",     "https://es.beincrypto.com/feed/",                     "es"),
    ("🇪🇸 CriptoNoticias",    "https://www.criptonoticias.com/feed/",                 "es"),
    ("🇺🇸 Cointelegraph EN",  "https://cointelegraph.com/rss",                       "en"),
    ("🇺🇸 CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/",     "en"),
    ("🇺🇸 Decrypt",           "https://decrypt.co/feed",                             "en"),
    ("🇺🇸 ForexLive",         "https://www.forexlive.com/feed/news",                 "en"),
]

# ──────────────────────────────────────────────────────────────
# CORS HEADERS
# ──────────────────────────────────────────────────────────────
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# ──────────────────────────────────────────────────────────────
# VERIFICACIÓN TELEGRAM
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
# API ENDPOINTS
# ──────────────────────────────────────────────────────────────
async def api_user_info(request: web.Request) -> web.Response:
    """Endpoint para la Mini App - verifica membresía"""
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    # Intentar obtener user_id
    uid = 0
    try:
        uid = int(request.rel_url.query.get("user_id", "0"))
    except ValueError:
        pass

    if uid == 0:
        init_data = request.rel_url.query.get("initData", "")
        if init_data:
            try:
                params = dict(parse_qsl(init_data, keep_blank_values=True))
                user_raw = json.loads(unquote(params.get("user", "{}")))
                uid = user_raw.get("id", 0)
            except Exception:
                pass

    if uid == 0:
        return web.json_response({"error": "missing user_id"}, status=400, headers=CORS)

    sub = await db.get_subscription(uid)
    if not sub:
        return web.json_response({
            "has_membership": False,
            "user_id": uid,
        }, headers=CORS)

    expiry_dt = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    now_dt = datetime.now(timezone.utc)
    seconds_left = max(0, int((expiry_dt - now_dt).total_seconds()))

    return web.json_response({
        "has_membership": True,
        "user_id": uid,
        "first_name": sub["first_name"] or "",
        "username": sub["username"] or "",
        "expiry": sub["expiry"],
        "seconds_left": seconds_left,
        "is_expired": now_dt > expiry_dt,
    }, headers=CORS)

async def api_news(request: web.Request) -> web.Response:
    """Endpoint de noticias para la Mini App"""
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    items = await refresh_news_cache()
    now = datetime.now(timezone.utc).timestamp()

    if not items:
        return web.json_response({"error": "no_data", "items": []}, status=503, headers=CORS)

    return web.json_response({
        "items": items[:20],
        "cached": True,
        "fetched_at": _news_cache["fetched_at"],
        "total": len(items),
    }, headers=CORS)

async def api_calendar(request: web.Request) -> web.Response:
    """Endpoint de calendario económico"""
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)

    now = datetime.now(timezone.utc).timestamp()
    cached = _calendar_cache

    if cached["fetched_at"] and (now - cached["fetched_at"]) < CALENDAR_CACHE_SECONDS:
        return web.json_response({
            "events": cached["events"],
            "cached": True,
        }, headers=CORS)

    try:
        cal_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(cal_url) as resp:
                events = await resp.json(content_type=None)

        _calendar_cache["events"] = events
        _calendar_cache["fetched_at"] = now

        return web.json_response({"events": events}, headers=CORS)

    except Exception as e:
        logger.warning(f"api_calendar error: {e}")
        if cached["events"]:
            return web.json_response({"events": cached["events"], "cached": True}, headers=CORS)
        return web.json_response({"error": "no_data", "events": []}, status=503, headers=CORS)

# ──────────────────────────────────────────────────────────────
# RSS HELPERS
# ──────────────────────────────────────────────────────────────
async def fetch_rss_items(session: aiohttp.ClientSession, name: str, url: str, max_items: int = 5) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VIPBot/2.0; +https://t.me/bot)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            raw = await resp.read()

        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            date = item.findtext("pubDate", "").strip()
            if title and link:
                items.append({"title": title, "link": link, "pubDate": date, "source": name})

        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                date = entry.findtext("atom:updated", "", ns).strip()
                if title and link:
                    items.append({"title": title, "link": link, "pubDate": date, "source": name})

        return items
    except Exception:
        return []

async def refresh_news_cache() -> list[dict]:
    now_ts = datetime.now(timezone.utc).timestamp()

    if _news_cache["fetched_at"] and (now_ts - _news_cache["fetched_at"]) < NEWS_CACHE_SECONDS:
        return _news_cache["items"]

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_rss_items(session, name, url) for name, url, _ in RSS_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for res in results:
        if isinstance(res, list):
            all_items.extend(res)

    if all_items:
        _news_cache["items"] = all_items
        _news_cache["fetched_at"] = now_ts

    return _news_cache["items"]

# ──────────────────────────────────────────────────────────────
# SERVIDOR HTTP
# ──────────────────────────────────────────────────────────────
async def start_api_server():
    app_http = web.Application()
    app_http.router.add_route("GET", "/api/user_info", api_user_info)
    app_http.router.add_route("OPTIONS", "/api/user_info", api_user_info)
    app_http.router.add_route("GET", "/api/news", api_news)
    app_http.router.add_route("OPTIONS", "/api/news", api_news)
    app_http.router.add_route("GET", "/api/calendar", api_calendar)
    app_http.router.add_route("OPTIONS", "/api/calendar", api_calendar)

    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    logger.info(f"🌐 API en puerto {API_PORT}")

# ──────────────────────────────────────────────────────────────
# ESTADOS DE CONVERSACIÓN
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

BROADCAST_FILTER = {}

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
    """Expulsa usuario del canal"""
    try:
        await bot.ban_chat_member(CHANNEL_ID, user_id)
        await bot.unban_chat_member(CHANNEL_ID, user_id)
        logger.info(f"👢 Expulsado {user_id} del canal")
    except TelegramError as e:
        logger.warning(f"Error expulsando {user_id}: {e}")

async def add_to_channel(bot, user_id: int) -> str | None:
    """Genera link de invitación al canal"""
    try:
        link = await bot.create_chat_invite_link(
            CHANNEL_ID,
            member_limit=1,
            expire_date=utc_now() + timedelta(minutes=5)
        )
        return link.invite_link
    except TelegramError as e:
        logger.warning(f"Error creando link para {user_id}: {e}")
        return None

async def notify_user(bot, user_id: int, text: str, **kwargs):
    try:
        await bot.send_message(user_id, text, **kwargs)
    except TelegramError as e:
        logger.warning(f"Error notificando {user_id}: {e}")

async def unique_code() -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "VIP-" + "".join(random.choices(chars, k=6))
        if not await db.code_exists(code):
            return code
    return "VIP-" + secrets.token_hex(4).upper()

# ──────────────────────────────────────────────────────────────
# CHECK BANEADOS
# ──────────────────────────────────────────────────────────────
async def check_banned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if await db.is_banned(user.id):
        target = update.message or (update.callback_query and update.callback_query.message)
        if target:
            try:
                await target.reply_text(msg.already_banned())
            except TelegramError:
                pass
        return True
    return False

# ──────────────────────────────────────────────────────────────
# HANDLER PRINCIPAL - START (VERSIÓN AMIGABLE CON NOMBRE)
# ──────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida cálido que dice el nombre del usuario"""
    if await check_banned(update, context):
        return

    user = update.effective_user

    # Verificar si ya tiene membresía activa
    sub = await db.get_subscription(user.id)
    if sub and days_left(sub["expiry"]) > 0:
        # Ya es miembro, mostrar menú completo (con nombre)
        await update.message.reply_text(
            f"✨ *¡Hola de nuevo, {user.first_name}!*\n\n"
            f"Tu membresía sigue activa. ¿Qué necesitas hacer hoy?",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Mensaje de bienvenida para nuevos usuarios (con nombre)
    welcome_text = (
        f"👋 *¡Hola {user.first_name}! Bienvenido al bot VIP*\n\n"
        f"Para acceder al canal exclusivo de copy trading, necesitas un código de activación.\n\n"
        f"🔑 *¿Tienes un código?*\n"
        f"Si ya tienes un código proporcionado por soporte, simplemente *pégalo aquí* y te daré acceso inmediato.\n\n"
        f"❓ *¿No tienes código?*\n"
        f"Contacta con el administrador para adquirir tu membresía.\n\n"
        f"✏️ *Escribe tu código VIP aquí* o usa el botón de abajo:"
    )

    # Botón para pegar código rápidamente
    keyboard = [[InlineKeyboardButton("🔑 Pegar mi código", callback_data="activate")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ──────────────────────────────────────────────────────────────
# ACTIVAR CÓDIGO - FLUJO AMIGABLE
# ──────────────────────────────────────────────────────────────
async def activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso de activación de código"""
    if await check_banned(update, context):
        return ConversationHandler.END

    # Puede venir de callback_query o mensaje directo
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(
            "🔑 *Activar código VIP*\n\n"
            "Por favor, escribe el código que te proporcionó soporte.\n\n"
            "✏️ *Ejemplo:* `VIP-ABC123`\n\n"
            "_El código es sensible a mayúsculas, escríbelo exactamente como te lo dieron._",
            reply_markup=kb.cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Ya viene de un mensaje directo
        await update.message.reply_text(
            "🔑 *Perfecto, dime tu código VIP:*\n\n"
            "Escríbelo exactamente como te lo dio soporte.",
            reply_markup=kb.cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )

    return STATE_ACTIVATE

async def activate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el código ingresado"""
    if await check_banned(update, context):
        return ConversationHandler.END

    user = update.effective_user
    code = update.message.text.strip().upper()

    # Mostrar "escribiendo..." para dar sensación de proceso
    await update.message.chat.send_action(action="typing")
    await asyncio.sleep(0.5)

    try:
        row = await db.get_code(code)
    except Exception as e:
        logger.error(f"Error DB: {e}")
        await update.message.reply_text(
            "❌ *Error interno*\n\n"
            "Hubo un problema al verificar el código. Por favor, intenta de nuevo en unos segundos.",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    # Código no válido
    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text(
            "❌ *Código inválido*\n\n"
            "El código que ingresaste no existe, ya fue usado o está desactivado.\n\n"
            "🔍 Verifica que lo escribiste correctamente o contacta a soporte.",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    # Código válido - procesar activación
    days = row["days"]

    # Verificar si ya tiene membresía
    sub = await db.get_subscription(user.id)
    if sub:
        # Sumar días a membresía existente
        current_exp = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        new_exp = max(current_exp, utc_now()) + timedelta(days=days)
    else:
        # Nueva membresía
        new_exp = utc_now() + timedelta(days=days)

    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    # Guardar en DB
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)

    # Si el código alcanzó su máximo de usos, desactivarlo
    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)

    # Generar link de invitación al canal
    await update.message.chat.send_action(action="typing")
    await asyncio.sleep(0.5)

    link = await add_to_channel(context.bot, user.id)

    # Mensaje de éxito AMIGABLE (con nombre)
    success_text = (
        f"✅ *¡Felicidades {user.first_name}!*\n\n"
        f"Tu código *{code}* ha sido activado correctamente.\n\n"
        f"📅 *Días agregados:* {days}\n"
        f"⏳ *Válido hasta:* {fmt_expiry(new_exp)}\n\n"
    )

    if link:
        success_text += (
            f"🔗 *Accede al canal VIP aquí:*\n"
            f"{link}\n\n"
            f"_El link es de un solo uso y expira en 5 minutos._"
        )
    else:
        success_text += (
            f"⚠️ *No pude generar el link automáticamente.*\n"
            f"Por favor, contacta a soporte para que te agreguen al canal."
        )

    success_text += (
        f"\n\n✨ Ya puedes usar todas las funciones del bot y la calculadora VIP."
    )

    await update.message.reply_text(
        success_text,
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

    # Log
    await db.log_event("activate", user.id, f"code={code} days={days}")
    logger.info(f"✅ Usuario {user.id} activó {code} (+{days} días)")

    return ConversationHandler.END

# ──────────────────────────────────────────────────────────────
# RENOVAR CÓDIGO
# ──────────────────────────────────────────────────────────────
async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🔄 *Renovar acceso*\n\n"
        "¿Tienes un código de renovación? Escríbelo aquí y sumaré días a tu membresía actual.\n\n"
        "✏️ *Escribe tu código:*",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_RENEW

async def renew_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip().upper()

    row = await db.get_code(code)

    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text(
            "❌ *Código inválido*\n\n"
            "El código no existe o ya fue usado.",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    sub = await db.get_subscription(user.id)
    if not sub:
        await update.message.reply_text(
            "⚠️ *No tienes membresía activa*\n\n"
            "Usa la opción *Activar código* primero para obtener tu primer acceso.",
            reply_markup=kb.main_menu(),
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
        f"✅ *¡Renovación exitosa!*\n\n"
        f"Se agregaron *{days} días* a tu membresía.\n"
        f"📅 Nueva fecha de vencimiento: `{fmt_expiry(new_exp)}`",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
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
        await q.edit_message_text(
            "⚠️ *Ya usaste tu prueba gratuita*\n\n"
            "Cada usuario puede usar la prueba gratis solo una vez.\n"
            "Adquiere un código VIP para continuar.",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    new_exp = utc_now() + timedelta(days=FREE_TRIAL_DAYS)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, FREE_TRIAL_DAYS, "FREE_TRIAL")
    await db.mark_trial_used(user.id)

    link = await add_to_channel(context.bot, user.id)

    reply_text = (
        f"🎁 *¡Prueba gratuita activada!*\n\n"
        f"Disfruta *{FREE_TRIAL_DAYS} días* de acceso VIP.\n"
        f"📅 Vence: `{fmt_expiry(new_exp)}`\n\n"
    )

    if link:
        reply_text += f"🔗 [Accede al canal aquí]({link})\n\n"

    reply_text += "_La prueba es por única vez. Aprovecha al máximo el contenido._"

    await q.edit_message_text(
        reply_text,
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

    await db.log_event("trial", user.id, f"days={FREE_TRIAL_DAYS}")

# ──────────────────────────────────────────────────────────────
# HISTORIAL (con nombre)
# ──────────────────────────────────────────────────────────────
async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return

    q = update.callback_query
    await q.answer()
    user = q.from_user

    events = await db.get_user_history(user.id)

    if not events:
        await q.edit_message_text(
            f"📜 *Historial de {user.first_name}*\n\n"
            "_Aún no tienes actividad registrada._\n\n"
            "Comienza activando un código o usando la prueba gratis.",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = f"📜 *Historial de {user.first_name}*\n\n"
    for e in events[:10]:
        txt += f"• `{e['created_at'][:16]}` — {e['event']}\n"

    await q.edit_message_text(txt, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# SOPORTE
# ──────────────────────────────────────────────────────────────
async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🎟️ *Centro de Soporte*\n\n"
        "¿Tienes algún problema o consulta?\n"
        "Crea un ticket y te responderemos a la brevedad.\n\n"
        "_Tiempo de respuesta: 24-48h_",
        reply_markup=kb.support_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

# ──────────────────────────────────────────────────────────────
# TICKETS - USUARIO
# ──────────────────────────────────────────────────────────────
async def ticket_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "✏️ *Nuevo ticket de soporte*\n\n"
        "Primero, ¿cuál es el *asunto* de tu consulta?\n"
        "_(Ej: Problema con acceso, código no funciona, duda general)_",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_TICKET_SUBJECT

async def ticket_subject_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ticket_subject"] = update.message.text.strip()[:100]

    await update.message.reply_text(
        "💬 *Describe tu problema*\n\n"
        "Cuéntanos con detalle qué sucede. Incluye toda la información que pueda ayudar a resolverlo más rápido.",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_TICKET_MESSAGE

async def ticket_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subject = context.user_data.get("ticket_subject", "Sin asunto")
    content = update.message.text.strip()

    ticket_id = await db.create_ticket(user.id, user.username or "", user.first_name, subject)
    await db.add_ticket_message(ticket_id, user.id, content, is_admin=False)
    await db.log_event("ticket", user.id, f"id={ticket_id}")

    await update.message.reply_text(
        f"✅ *Ticket #{ticket_id:04d} creado*\n\n"
        f"📌 Asunto: _{subject}_\n\n"
        "Te notificaremos cuando tengamos una respuesta. ¡Gracias por tu paciencia!",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

    # Notificar a admins
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(
            context.bot, aid,
            f"🎟️ *Nuevo ticket #{ticket_id:04d}*\n"
            f"👤 {user.first_name} (`{user.id}`)\n"
            f"📌 {subject}\n\n"
            f"{content[:200]}...",
            reply_markup=kb.admin_ticket_actions(ticket_id, True)
        )

    return ConversationHandler.END

async def ticket_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return

    q = update.callback_query
    await q.answer()

    tickets = await db.get_user_tickets(q.from_user.id)

    if not tickets:
        await q.edit_message_text(
            "📭 *No tienes tickets abiertos*",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "🎟️ *Tus tickets*\n\n"
    btns = []

    for t in tickets[:10]:
        status = "🟢" if t["status"] == "open" else "⚫"
        txt += f"{status} *#{t['id']:04d}* — {t['subject'][:40]}\n"
        btns.append([InlineKeyboardButton(f"Ticket #{t['id']:04d}", callback_data=f"ticket_view_{t['id']}")])

    btns.append([InlineKeyboardButton("← Menú principal", callback_data="main_menu")])

    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def ticket_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    ticket = await db.get_ticket(tid)

    if not ticket or ticket["user_id"] != q.from_user.id:
        await q.answer("❌ Ticket no encontrado", show_alert=True)
        return

    messages = await db.get_ticket_messages(tid)

    txt = f"🎟️ *Ticket #{tid:04d}*\n"
    txt += f"📌 {ticket['subject']}\n"
    txt += f"🔘 Estado: {'🟢 Abierto' if ticket['status'] == 'open' else '⚫ Cerrado'}\n\n"

    for m in messages[-5:]:
        who = "👤 Tú" if not m["is_admin"] else "🛡️ Soporte"
        txt += f"*{who}* `{m['sent_at'][:16]}`\n{m['message'][:200]}\n\n"

    btns = []
    if ticket["status"] == "open":
        btns.append([InlineKeyboardButton("💬 Responder", callback_data=f"ticket_reply_{tid}")])
        btns.append([InlineKeyboardButton("✅ Cerrar ticket", callback_data=f"ticket_close_{tid}")])
    else:
        btns.append([InlineKeyboardButton("🔄 Reabrir", callback_data=f"ticket_reopen_{tid}")])

    btns.append([InlineKeyboardButton("← Mis tickets", callback_data="ticket_list")])

    await q.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    context.user_data["reply_ticket_id"] = tid

    await q.edit_message_text(
        f"✍️ *Responder al ticket #{tid:04d}*\n\n"
        f"Escribe tu mensaje:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_TICKET_REPLY_USER

async def ticket_reply_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tid = context.user_data.get("reply_ticket_id")

    if not tid:
        return ConversationHandler.END

    await db.add_ticket_message(tid, user.id, update.message.text.strip(), is_admin=False)

    await update.message.reply_text(
        f"✅ *Respuesta enviada al ticket #{tid:04d}*",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

    # Notificar admins
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(
            context.bot, aid,
            f"🔔 *Nueva respuesta en ticket #{tid:04d}*\n"
            f"👤 {user.first_name}\n\n"
            f"{update.message.text.strip()[:200]}",
            reply_markup=kb.admin_ticket_actions(tid, True)
        )

    return ConversationHandler.END

async def ticket_close_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)

    await q.edit_message_text(
        f"✅ *Ticket #{tid:04d} cerrado*\n\n"
        f"Si necesitas más ayuda, puedes abrir un nuevo ticket.",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

async def ticket_reopen_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)

    await q.edit_message_text(
        f"🔄 *Ticket #{tid:04d} reabierto*",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

# ──────────────────────────────────────────────────────────────
# ADMIN - TICKETS
# ──────────────────────────────────────────────────────────────
async def adm_tickets(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    open_c = len(await db.get_open_tickets())

    await q.edit_message_text(
        f"🎟️ *Gestión de Tickets*\n\n"
        f"📂 Tickets abiertos: *{open_c}*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 Ver abiertos", callback_data="adm_tickets_open")],
            [InlineKeyboardButton("📋 Ver todos", callback_data="adm_tickets_all")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_tickets_open(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    tickets = await db.get_open_tickets()

    if not tickets:
        await q.edit_message_text(
            "✅ *Sin tickets abiertos*",
            reply_markup=kb.admin_back()
        )
        return

    btns = [[InlineKeyboardButton(f"#{t['id']:04d} {t['subject'][:25]}", callback_data=f"adm_tview_{t['id']}")] for t in tickets[:10]]
    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])

    await q.edit_message_text(
        "🟢 *Tickets abiertos*",
        reply_markup=InlineKeyboardMarkup(btns),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_tickets_all(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    tickets = await db.get_all_tickets(20)

    btns = []
    for t in tickets:
        icon = "🟢" if t["status"] == "open" else "⚫"
        btns.append([InlineKeyboardButton(f"{icon} #{t['id']:04d} {t['subject'][:20]}", callback_data=f"adm_tview_{t['id']}")])

    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])

    await q.edit_message_text(
        "📋 *Todos los tickets*",
        reply_markup=InlineKeyboardMarkup(btns),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_ticket_view(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    ticket = await db.get_ticket(tid)

    if not ticket:
        await q.answer("❌ Ticket no encontrado", show_alert=True)
        return

    msgs = await db.get_ticket_messages(tid)

    txt = f"🎟️ *Ticket #{tid:04d}*\n"
    txt += f"👤 {ticket['first_name']} (`{ticket['user_id']}`)\n"
    txt += f"📌 {ticket['subject']}\n"
    txt += f"🔘 Estado: {'🟢 Abierto' if ticket['status'] == 'open' else '⚫ Cerrado'}\n\n"

    for m in msgs[-6:]:
        who = "🛡️ Admin" if m["is_admin"] else "👤 Usuario"
        txt += f"*{who}* `{m['sent_at'][:16]}`\n{m['message'][:200]}\n\n"

    await q.edit_message_text(
        txt[:4000],
        reply_markup=kb.admin_ticket_actions(tid, ticket["status"] == "open"),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_ticket_reply_start(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    context.user_data["adm_reply_ticket"] = tid

    await q.edit_message_text(
        f"✍️ *Responder al ticket #{tid:04d}*\n\n"
        f"Escribe tu respuesta:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_ADM_TICKET_REPLY

async def adm_ticket_reply_message(update, context):
    admin = update.effective_user
    tid = context.user_data.get("adm_reply_ticket")

    if not tid:
        return ConversationHandler.END

    ticket = await db.get_ticket(tid)
    await db.add_ticket_message(tid, admin.id, update.message.text.strip(), is_admin=True)

    await update.message.reply_text(
        f"✅ *Respuesta enviada al ticket #{tid:04d}*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

    if ticket:
        await notify_user(
            context.bot, ticket["user_id"],
            f"🔔 *Nueva respuesta en tu ticket #{tid:04d}*\n\n"
            f"{update.message.text.strip()[:500]}",
            reply_markup=kb.main_menu()
        )

    return ConversationHandler.END

async def adm_ticket_close(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)

    await q.edit_message_text(
        f"✅ *Ticket #{tid:04d} cerrado*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_ticket_reopen(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)

    await q.edit_message_text(
        f"🔄 *Ticket #{tid:04d} reabierto*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

# ──────────────────────────────────────────────────────────────
# ADMIN - PANEL PRINCIPAL
# ──────────────────────────────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 No tienes permisos para usar este comando.")
        return

    await update.message.reply_text(
        "🛡️ *Panel de Administración*\n\n"
        "Bienvenido al panel de control. Selecciona una opción:",
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🛡️ *Panel de Administración*",
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_gen_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🔑 *Generar código VIP*\n\n"
        "Selecciona la duración del código:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 7 días", callback_data="adm_quick_7"),
             InlineKeyboardButton("📅 15 días", callback_data="adm_quick_15")],
            [InlineKeyboardButton("📅 30 días", callback_data="adm_quick_30"),
             InlineKeyboardButton("📅 60 días", callback_data="adm_quick_60")],
            [InlineKeyboardButton("📅 90 días", callback_data="adm_quick_90"),
             InlineKeyboardButton("✏️ Personalizado", callback_data="adm_quick_custom")],
            [InlineKeyboardButton("← Panel", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_GEN_CODE

async def adm_gen_code_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    data = q.data.split("_")[-1]

    if data == "custom":
        await q.edit_message_text(
            "✏️ *Código personalizado*\n\n"
            "Formato: `días usos [nota]`\n"
            "Ejemplo: `30 5 Clientes junio`",
            reply_markup=kb.cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return STATE_GEN_CODE

    days = int(data)
    code = await unique_code()
    await db.create_code(code, days, 1, created_by=q.from_user.id)
    await db.audit(q.from_user.id, "gen_code", code, f"days={days}")

    await q.edit_message_text(
        f"✅ *Código generado*\n\n"
        f"🔑 `{code}`\n"
        f"📅 Días: *{days}*\n"
        f"👤 Usos: *1*\n\n"
        f"Envía este código al usuario.",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_gen_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    parts = update.message.text.strip().split()
    try:
        days = int(parts[0])
        uses = int(parts[1]) if len(parts) > 1 else 1
        note = " ".join(parts[2:]) if len(parts) > 2 else ""
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ *Formato inválido*\n\n"
            "Usa: `días usos [nota]`\n"
            "Ejemplo: `30 5 Clientes`",
            parse_mode=ParseMode.MARKDOWN
        )
        return STATE_GEN_CODE

    code = await unique_code()
    await db.create_code(code, days, uses, note, created_by=update.effective_user.id)
    await db.audit(update.effective_user.id, "gen_code", code, f"days={days} uses={uses}")

    await update.message.reply_text(
        f"✅ *Código generado*\n\n"
        f"🔑 `{code}`\n"
        f"📅 Días: *{days}*\n"
        f"👤 Usos: *{uses}*\n"
        f"📝 Nota: {note if note else 'Sin nota'}",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_list_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    codes = await db.get_active_codes()

    if not codes:
        await q.edit_message_text(
            "📭 *Sin códigos activos*",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "🔑 *Códigos activos*\n\n"
    for c in codes[:20]:
        remaining = c['max_uses'] - c['used_count']
        txt += f"`{c['code']}` — {c['days']}d — {remaining}/{c['max_uses']} usos\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    members = await db.get_all_subscriptions()

    if not members:
        await q.edit_message_text(
            "👥 *Sin miembros registrados*",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = f"👥 *Miembros activos ({len(members)})*\n\n"
    for m in members[:20]:
        d = days_left(m["expiry"])
        emoji = "🟢" if d > 3 else ("🟡" if d > 1 else "🔴")
        txt += f"{emoji} {m['first_name']} (`{m['user_id']}`) — {d}d\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    s = await db.get_stats_summary()

    txt = (
        f"📊 *Estadísticas*\n\n"
        f"👥 Total miembros: *{s['total']}*\n"
        f"✅ Activos: *{s['active']}*\n"
        f"🆕 Nuevos hoy: *{s['new_today']}*\n"
        f"⚠️ Vencen en 3d: *{s['expiring_3d']}*\n"
        f"🔑 Códigos activos: *{s['codes']}*\n"
        f"🎟️ Tickets abiertos: *{s['tickets_open']}*\n"
        f"🚫 Bloqueados: *{s['banned']}*\n"
        f"🎁 Pruebas usadas: *{s['trials']}*"
    )

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    rank = await db.get_ranking(10)

    if not rank:
        await q.edit_message_text(
            "🏆 *Ranking VIP*\n\n"
            "Sin datos todavía.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "🏆 *Top 10 VIP*\n\n"
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]

    for i, m in enumerate(rank):
        txt += f"{medals[i]} {m['first_name']} — *{m['total_days']}d*\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "📢 *Broadcast*\n\n"
        "¿A quién quieres enviar el mensaje?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Todos los miembros", callback_data="adm_bc_all")],
            [InlineKeyboardButton("✅ Solo activos", callback_data="adm_bc_active")],
            [InlineKeyboardButton("⚠️ Por vencer (3d)", callback_data="adm_bc_expiring")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_broadcast_segment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    seg = q.data.replace("adm_bc_", "")
    BROADCAST_FILTER["segment"] = seg

    await q.edit_message_text(
        f"✍️ *Escribe el mensaje*\n\n"
        f"Segmento seleccionado: *{seg}*\n\n"
        f"Redacta el mensaje que quieres enviar:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_BROADCAST_MSG

async def adm_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seg = BROADCAST_FILTER.get("segment", "all")
    context.user_data["bc_message"] = update.message.text.strip()

    await update.message.reply_text(
        f"📢 *Vista previa*\n\n"
        f"Segmento: *{seg}*\n\n"
        f"{context.user_data['bc_message']}\n\n"
        f"¿Enviar ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enviar", callback_data="adm_broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer("📤 Enviando mensajes...")

    seg = BROADCAST_FILTER.get("segment", "all")
    txt = context.user_data.get("bc_message", "")

    if not txt:
        await q.edit_message_text(
            "❌ Error: mensaje vacío",
            reply_markup=kb.admin_back()
        )
        return

    # Obtener miembros según segmento
    if seg == "active":
        members = [m for m in await db.get_all_subscriptions() if days_left(m["expiry"]) > 0]
    elif seg == "expiring":
        members = await db.get_expiring_soon(72)
    else:
        members = await db.get_all_subscriptions()

    # Enviar mensajes
    ok, fail = 0, 0
    await q.edit_message_text(f"📤 Enviando a {len(members)} usuarios...")

    for m in members:
        try:
            await context.bot.send_message(m["user_id"], txt, parse_mode=ParseMode.MARKDOWN)
            ok += 1
        except TelegramError:
            fail += 1
        await asyncio.sleep(0.05)  # Pequeña pausa para evitar floods

    await db.log_broadcast(txt, seg, ok, fail)

    await q.edit_message_text(
        f"✅ *Broadcast completado*\n\n"
        f"📨 Enviados: *{ok}*\n"
        f"❌ Fallidos: *{fail}*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_admins(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "👑 *Gestión de administradores*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Agregar admin", callback_data="adm_add_admin")],
            [InlineKeyboardButton("➖ Remover admin", callback_data="adm_remove_admin")],
            [InlineKeyboardButton("📋 Listar admins", callback_data="adm_list_admins")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_list_admins(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    admins = await db.list_admins()

    txt = f"👑 *Administradores*\n\n"
    txt += f"⭐ Admin principal: `{ADMIN_ID}`\n\n"

    if admins:
        for a in admins:
            txt += f"• {a['first_name']} (`{a['user_id']}`)\n"
    else:
        txt += "_No hay admins secundarios._"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_add_admin_start(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "✏️ *Agregar admin*\n\n"
        "Escribe el *user_id* del nuevo administrador:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_ADD_ADMIN

async def adm_add_admin_received(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    try:
        new_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ ID inválido. Debe ser un número.",
            parse_mode=ParseMode.MARKDOWN
        )
        return STATE_ADD_ADMIN

    await db.add_admin(new_id, "", "", update.effective_user.id)
    await db.audit(update.effective_user.id, "add_admin", str(new_id))

    await update.message.reply_text(
        f"✅ *Admin agregado*\n\n"
        f"Usuario `{new_id}` ahora es administrador.",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_remove_admin_start(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "✏️ *Remover admin*\n\n"
        "Escribe el *user_id* del administrador a remover:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_REMOVE_ADMIN

async def adm_remove_admin_received(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    try:
        rem_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ ID inválido. Debe ser un número.",
            parse_mode=ParseMode.MARKDOWN
        )
        return STATE_REMOVE_ADMIN

    if rem_id == ADMIN_ID:
        await update.message.reply_text(
            "❌ No puedes remover al admin principal.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await db.remove_admin(rem_id)
    await db.audit(update.effective_user.id, "remove_admin", str(rem_id))

    await update.message.reply_text(
        f"✅ *Admin removido*\n\n"
        f"Usuario `{rem_id}` ya no es administrador.",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_blacklist(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🚫 *Lista negra*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Banear usuario", callback_data="adm_ban_input")],
            [InlineKeyboardButton("📋 Ver lista", callback_data="adm_blacklist_list")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_ban_input_start(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "✏️ *Banear usuario*\n\n"
        "Escribe el *user_id* del usuario a banear:",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_BAN_INPUT

async def adm_ban_input_received(update, context):
    if not await is_admin(update.effective_user.id):
        return ConversationHandler.END

    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "❌ ID inválido. Debe ser un número.",
            parse_mode=ParseMode.MARKDOWN
        )
        return STATE_BAN_INPUT

    await db.ban_user(uid, "Ban desde panel", update.effective_user.id)
    await kick_from_channel(context.bot, uid)
    await db.audit(update.effective_user.id, "ban", str(uid))

    await update.message.reply_text(
        f"🚫 *Usuario baneado*\n\n"
        f"Usuario `{uid}` agregado a la lista negra.",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_blacklist_list(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    bl = await db.get_blacklist()

    if not bl:
        await q.edit_message_text(
            "✅ *Lista negra vacía*\n\n"
            "No hay usuarios baneados.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "🚫 *Usuarios baneados*\n\n"
    for b in bl[:20]:
        txt += f"• `{b['user_id']}` — {b['reason'] or 'Sin razón'}\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_clean_expired(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer("🧹 Limpiando...")

    expired = await db.get_expired_members()

    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])

    await q.edit_message_text(
        f"✅ *Limpieza completada*\n\n"
        f"Se eliminaron *{len(expired)}* miembros vencidos.",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_export_csv(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer("📤 Generando CSV...")

    csv_data = await db.export_members_csv()

    await context.bot.send_document(
        q.from_user.id,
        document=io.BytesIO(csv_data.encode()),
        filename=f"miembros_{datetime.now().strftime('%Y%m%d')}.csv",
        caption="📊 Exportación de miembros"
    )

    await q.edit_message_text(
        "✅ *CSV enviado*",
        reply_markup=kb.admin_back(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_backup(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer("💾 Generando backup...")

    try:
        with open("vip_bot.db", "rb") as f:
            await context.bot.send_document(
                q.from_user.id,
                document=f,
                filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
                caption="🗄️ Backup de base de datos"
            )

        await q.edit_message_text(
            "✅ *Backup enviado*",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await q.edit_message_text(
            f"❌ Error: {str(e)}",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )

async def adm_audit_log(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    logs = await db.get_audit_log(30)

    if not logs:
        await q.edit_message_text(
            "📋 *Log de auditoría*\n\n"
            "Sin registros.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "📋 *Últimas acciones*\n\n"
    for l in logs:
        txt += f"`{l['created_at'][:16]}` *{l['action']}* {l['target'] or ''}\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast_history(update, context):
    if not await is_admin(update.effective_user.id):
        return

    q = update.callback_query
    await q.answer()

    history = await db.get_broadcast_history(10)

    if not history:
        await q.edit_message_text(
            "📜 *Historial de broadcasts*\n\n"
            "Sin registros.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    txt = "📜 *Últimos broadcasts*\n\n"
    for b in history:
        txt += f"`{b['created_at'][:16]}` [{b['filter_type']}] ✅{b['sent_to']} ❌{b['failed']}\n"

    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# COMANDOS DIRECTOS (ADMIN)
# ──────────────────────────────────────────────────────────────
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Uso: /ban <user_id> [razón]")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido")
        return

    reason = " ".join(args[1:]) or "Sin razón"
    await db.ban_user(uid, reason, update.effective_user.id)
    await kick_from_channel(context.bot, uid)

    await update.message.reply_text(f"🚫 Usuario `{uid}` baneado.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Uso: /unban <user_id>")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido")
        return

    await db.unban_user(uid)
    await update.message.reply_text(f"✅ Usuario `{uid}` desbaneado.")

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /adddays <user_id> <días>")
        return

    try:
        uid = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Valores inválidos")
        return

    sub = await db.get_subscription(uid)
    if not sub:
        await update.message.reply_text(f"❌ Usuario `{uid}` sin membresía")
        return

    await db.add_days_to_subscription(uid, days)
    await db.audit(update.effective_user.id, "adddays", str(uid), f"+{days}d")

    await update.message.reply_text(f"✅ +{days} días a `{uid}`")

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Uso: /addadmin <user_id>")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido")
        return

    await db.add_admin(uid, "", "", update.effective_user.id)
    await update.message.reply_text(f"✅ Admin `{uid}` agregado.")

async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Uso: /removeadmin <user_id>")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id inválido")
        return

    if uid == ADMIN_ID:
        await update.message.reply_text("❌ No puedes remover al admin principal")
        return

    await db.remove_admin(uid)
    await update.message.reply_text(f"✅ Admin `{uid}` removido.")

# ──────────────────────────────────────────────────────────────
# AUTO-RESPUESTA (Mensajes sin comando)
# ──────────────────────────────────────────────────────────────
async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return

    user = update.effective_user
    text = (update.message.text or "").lower()

    # Verificar si ya tiene membresía
    sub = await db.get_subscription(user.id)
    if not sub or days_left(sub["expiry"]) <= 0:
        # No tiene membresía, redirigir a activación
        await update.message.reply_text(
            f"👋 *Hola {user.first_name}*\n\n"
            f"Para usar el bot, primero necesitas activar un código VIP.\n\n"
            f"🔑 Por favor, escribe tu código aquí:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Activar código", callback_data="activate")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Respuestas rápidas para miembros (con nombre)
    responses = {
        ("hola", "hi", "buenas", "hey"): f"👋 ¡Hola {user.first_name}! ¿En qué puedo ayudarte?",
        ("gracias", "thanks", "ty"): f"🙌 ¡Con gusto, {user.first_name}!",
        ("menu", "menú"): "📍 Usa los botones del menú para navegar.",
        ("codigo", "código", "activar"): "🔑 Ve a *Activar código* en el menú.",
        ("canal", "acceso"): "📢 El link de acceso está en tu mensaje de activación.",
    }

    for keywords, reply in responses.items():
        if any(k in text for k in keywords):
            await update.message.reply_text(reply, reply_markup=kb.main_menu())
            return

    # Respuesta genérica (con nombre)
    await update.message.reply_text(
        f"💬 *Hola {user.first_name}*\n\n"
        f"Usa los botones del menú para acceder a las funciones del bot.",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

# ──────────────────────────────────────────────────────────────
# JOBS AUTOMÁTICOS
# ──────────────────────────────────────────────────────────────
async def job_clean_expired(context: ContextTypes.DEFAULT_TYPE):
    """Cada hora: expulsa miembros vencidos"""
    expired = await db.get_expired_members()

    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])

        try:
            await context.bot.send_message(
                m["user_id"],
                "⏰ *Tu membresía ha vencido*\n\n"
                "Has sido removido del canal VIP.\n"
                "Activa un nuevo código para recuperar el acceso.",
                parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError:
            pass

    if expired:
        logger.info(f"🧹 Limpieza: {len(expired)} miembros eliminados")

async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE):
    """Cada 12h: avisa a los que vencen pronto"""
    for hours in [72, 24, 1]:
        members = await db.get_expiring_soon(hours)

        for m in members:
            d_left = days_left(m["expiry"])

            if hours == 72:
                text = (
                    f"⚠️ *Tu membresía vence en 3 días*\n\n"
                    f"📅 Vencimiento: `{m['expiry'][:16]}`\n"
                    f"⏳ Días restantes: *{d_left}*\n\n"
                    f"Renueva pronto para no perder acceso."
                )
            elif hours == 24:
                text = (
                    f"🔔 *Tu membresía vence MAÑANA*\n\n"
                    f"📅 Vencimiento: `{m['expiry'][:16]}`\n"
                    f"⏳ Días restantes: *{d_left}*\n\n"
                    f"¡Renueva hoy mismo!"
                )
            else:
                text = (
                    f"🚨 *¡ÚLTIMAS HORAS!*\n\n"
                    f"Tu membresía vence en *menos de 1 hora*.\n"
                    f"Renueva ahora para no perder el acceso."
                )

            await notify_user(context.bot, m["user_id"], text, reply_markup=kb.main_menu())

async def job_calendar_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Cada 15 min: alertas de alto impacto"""
    global _alerted_events, _calendar_cache

    now_ts = datetime.now(timezone.utc).timestamp()

    # Refrescar caché si es necesario
    if not _calendar_cache["fetched_at"] or (now_ts - _calendar_cache["fetched_at"]) > CALENDAR_CACHE_SECONDS:
        try:
            cal_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            async with aiohttp.ClientSession() as session:
                async with session.get(cal_url) as resp:
                    events = await resp.json()
            _calendar_cache["events"] = events
            _calendar_cache["fetched_at"] = now_ts
        except Exception as e:
            logger.warning(f"Error calendario: {e}")
            return

    now = datetime.now(timezone.utc)
    alert_window = now + timedelta(minutes=35)

    # Buscar eventos de alto impacto
    upcoming = []
    for ev in _calendar_cache.get("events", []):
        if ev.get("impact", "").lower() != "high":
            continue

        try:
            ev_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        except Exception:
            continue

        if now <= ev_dt <= alert_window:
            ev_id = f"{ev.get('title')}_{ev_dt.strftime('%Y%m%d%H%M')}"
            if ev_id not in _alerted_events:
                upcoming.append((ev, ev_dt, ev_id))

    if not upcoming:
        return

    # Obtener miembros activos
    members = await db.get_active_members()
    if not members:
        return

    # Enviar alertas
    flags = {
        "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
        "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CHF": "🇨🇭",
    }

    for ev, ev_dt, ev_id in upcoming:
        mins = int((ev_dt - now).total_seconds() / 60)
        flag = flags.get(ev.get("country", ""), "🌐")

        text = (
            f"🔴 *ALERTA - ALTO IMPACTO*\n\n"
            f"📌 *{ev.get('title')}*\n"
            f"{flag} {ev.get('country')}  |  🕐 {ev_dt.strftime('%H:%M')} UTC\n"
            f"⏱ En *{mins} minutos*\n\n"
            f"Prepárate para alta volatilidad."
        )

        sent = 0
        for m in members:
            try:
                await context.bot.send_message(m["user_id"], text, parse_mode=ParseMode.MARKDOWN)
                sent += 1
            except TelegramError:
                pass

        _alerted_events.add(ev_id)
        logger.info(f"📢 Alerta: {ev.get('title')} → {sent} usuarios")

async def job_crypto_news(context: ContextTypes.DEFAULT_TYPE):
    """Cada 30 min: publica noticias en el canal"""
    global _seen_news_links

    items = await refresh_news_cache()
    if not items:
        return

    # Noticias nuevas
    new_items = [it for it in items if it.get("link") and it["link"] not in _seen_news_links]

    if not new_items:
        return

    # Publicar máx 3 por ciclo
    for item in new_items[:3]:
        title = item.get("title", "").strip()
        link = item.get("link", "").strip()
        source = item.get("source", "Crypto News")

        if not title or not link:
            continue

        text = (
            f"📰 *{title}*\n\n"
            f"📡 {source}\n\n"
            f"🔗 {link}"
        )

        try:
            await context.bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
            _seen_news_links.add(link)
            await asyncio.sleep(2)
        except TelegramError as e:
            logger.warning(f"Error publicando: {e}")

    # Limpiar caché de links (mantener últimos 200)
    if len(_seen_news_links) > 200:
        _seen_news_links = set(list(_seen_news_links)[-200:])

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    """Resumen diario para admins"""
    stats = await db.get_stats_summary()
    admin_ids = await db.get_all_admin_ids()

    text = (
        f"📊 *Resumen diario*\n\n"
        f"👥 Activos: *{stats['active']}*\n"
        f"📆 Nuevos hoy: *{stats['new_today']}*\n"
        f"⚠️ Vencen pronto: *{stats['expiring_3d']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*"
    )

    for aid in admin_ids:
        await notify_user(context.bot, aid, text)

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    async def _run():
        # Inicializar DB
        await db.init_db()

        if not BOT_TOKEN:
            logger.critical("BOT_TOKEN no configurado")
            return

        # Iniciar servidor API
        await start_api_server()

        # Crear aplicación
        app = Application.builder().token(BOT_TOKEN).build()

        # ── Conversaciones ──
        convs = [
            # Activación de código
            ConversationHandler(
                entry_points=[
                    CallbackQueryHandler(activate_start, pattern="^activate$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, activate_start)
                ],
                states={STATE_ACTIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            # Renovación
            ConversationHandler(
                entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
                states={STATE_RENEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            # Admin: generar código
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_gen_code_menu, pattern="^adm_gen_code$")],
                states={STATE_GEN_CODE: [
                    CallbackQueryHandler(adm_gen_code_quick, pattern="^adm_quick_"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gen_code_input)
                ]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Admin: banear
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_ban_input_start, pattern="^adm_ban_input$")],
                states={STATE_BAN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ban_input_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Admin: broadcast
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_broadcast_segment, pattern="^adm_bc_")],
                states={STATE_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_preview)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Tickets: nuevo
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_new_start, pattern="^ticket_new$")],
                states={
                    STATE_TICKET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_subject_received)],
                    STATE_TICKET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_message_received)],
                },
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            # Tickets: responder usuario
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_reply_start, pattern="^ticket_reply_")],
                states={STATE_TICKET_REPLY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_reply_user_message)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            # Tickets: responder admin
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_ticket_reply_start, pattern="^adm_ticket_reply_")],
                states={STATE_ADM_TICKET_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ticket_reply_message)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Admin: agregar admin
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_add_admin_start, pattern="^adm_add_admin$")],
                states={STATE_ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Admin: remover admin
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_remove_admin_start, pattern="^adm_remove_admin$")],
                states={STATE_REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_remove_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
        ]

        for conv in convs:
            app.add_handler(conv)

        # ── Comandos ──
        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("admin", admin_command))
        app.add_handler(CommandHandler("ban", ban_command))
        app.add_handler(CommandHandler("unban", unban_command))
        app.add_handler(CommandHandler("adddays", adddays_command))
        app.add_handler(CommandHandler("addadmin", addadmin_command))
        app.add_handler(CommandHandler("removeadmin", removeadmin_command))

        # ── Callbacks de usuario ──
        app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
        app.add_handler(CallbackQueryHandler(free_trial_callback, pattern="^free_trial$"))
        app.add_handler(CallbackQueryHandler(history_callback, pattern="^history$"))
        app.add_handler(CallbackQueryHandler(support_callback, pattern="^support$"))
        app.add_handler(CallbackQueryHandler(ticket_list_callback, pattern="^ticket_list$"))
        app.add_handler(CallbackQueryHandler(ticket_view_callback, pattern="^ticket_view_"))
        app.add_handler(CallbackQueryHandler(ticket_close_user, pattern="^ticket_close_"))
        app.add_handler(CallbackQueryHandler(ticket_reopen_user, pattern="^ticket_reopen_"))

        # ── Callbacks de admin ──
        app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$"))
        app.add_handler(CallbackQueryHandler(adm_list_codes, pattern="^adm_list_codes$"))
        app.add_handler(CallbackQueryHandler(adm_members, pattern="^adm_members$"))
        app.add_handler(CallbackQueryHandler(adm_stats, pattern="^adm_stats$"))
        app.add_handler(CallbackQueryHandler(adm_ranking, pattern="^adm_ranking$"))
        app.add_handler(CallbackQueryHandler(adm_admins, pattern="^adm_admins$"))
        app.add_handler(CallbackQueryHandler(adm_list_admins, pattern="^adm_list_admins$"))
        app.add_handler(CallbackQueryHandler(adm_blacklist, pattern="^adm_blacklist$"))
        app.add_handler(CallbackQueryHandler(adm_blacklist_list, pattern="^adm_blacklist_list$"))
        app.add_handler(CallbackQueryHandler(adm_broadcast, pattern="^adm_broadcast$"))
        app.add_handler(CallbackQueryHandler(adm_broadcast_confirm, pattern="^adm_broadcast_confirm$"))
        app.add_handler(CallbackQueryHandler(adm_clean_expired, pattern="^adm_clean_expired$"))
        app.add_handler(CallbackQueryHandler(adm_export_csv, pattern="^adm_export_csv$"))
        app.add_handler(CallbackQueryHandler(adm_backup, pattern="^adm_backup$"))
        app.add_handler(CallbackQueryHandler(adm_audit_log, pattern="^adm_audit_log$"))
        app.add_handler(CallbackQueryHandler(adm_broadcast_history, pattern="^adm_broadcast_history$"))
        app.add_handler(CallbackQueryHandler(adm_tickets, pattern="^adm_tickets$"))
        app.add_handler(CallbackQueryHandler(adm_tickets_open, pattern="^adm_tickets_open$"))
        app.add_handler(CallbackQueryHandler(adm_tickets_all, pattern="^adm_tickets_all$"))
        app.add_handler(CallbackQueryHandler(adm_ticket_view, pattern="^adm_tview_"))
        app.add_handler(CallbackQueryHandler(adm_ticket_close, pattern="^adm_ticket_close_"))
        app.add_handler(CallbackQueryHandler(adm_ticket_reopen, pattern="^adm_ticket_reopen_"))

        # ── Auto-respuesta ──
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply))

        # ── Jobs automáticos ──
        jq = app.job_queue
        jq.run_repeating(job_clean_expired, interval=3600, first=60)
        jq.run_repeating(job_warn_expiring, interval=43200, first=120)
        jq.run_repeating(job_calendar_alerts, interval=900, first=30)
        jq.run_repeating(job_crypto_news, interval=1800, first=90)
        jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time())

        logger.info(f"🚀 Bot iniciado | Canal: {CHANNEL_ID}")

        # Iniciar bot
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Manejar señales de parada
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
