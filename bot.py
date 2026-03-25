"""
bot.py — VIP Bot · Versión final con gestión de admins y sin noticias/calendario
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
import time
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
# CONFIGURACIÓN
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
# CACHÉ EN MEMORIA (para admin)
# ──────────────────────────────────────────────────────────────
_admin_cache = {
    "codes": {"data": None, "timestamp": 0},
    "members": {"data": None, "timestamp": 0},
    "blacklist": {"data": None, "timestamp": 0},
}
CACHE_DURATION = 60  # segundos

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
# API ENDPOINTS (solo user_info)
# ──────────────────────────────────────────────────────────────
async def api_user_info(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS)
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
        return web.json_response({"has_membership": False, "user_id": uid}, headers=CORS)
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
        "total_days": sub["total_days"] or 0,
        "is_expired": now_dt > expiry_dt,
    }, headers=CORS)

# ──────────────────────────────────────────────────────────────
# SERVIDOR HTTP
# ──────────────────────────────────────────────────────────────
async def start_api_server():
    app_http = web.Application()
    app_http.router.add_route("GET", "/api/user_info", api_user_info)
    app_http.router.add_route("OPTIONS", "/api/user_info", api_user_info)
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
    STATE_ADDDAYS_INPUT,
    STATE_KICK_MEMBER,
    STATE_ADMIN_ADD,
    STATE_ADMIN_REMOVE,
) = range(14)

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
    try:
        await bot.ban_chat_member(CHANNEL_ID, user_id)
        await bot.unban_chat_member(CHANNEL_ID, user_id)
        logger.info(f"👢 Expulsado {user_id} del canal")
    except TelegramError as e:
        logger.warning(f"Error expulsando {user_id}: {e}")

async def add_to_channel(bot, user_id: int) -> str | None:
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
# MENÚ PRINCIPAL
# ──────────────────────────────────────────────────────────────
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user
    await q.edit_message_text(
        f"✨ *Hola {user.first_name}*\n\nSelecciona una opción del menú:",
        reply_markup=kb.main_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    user = update.effective_user
    sub = await db.get_subscription(user.id)
    if sub and days_left(sub["expiry"]) > 0:
        await update.message.reply_text(
            f"✨ *¡Hola de nuevo, {user.first_name}!*\n\nTu membresía sigue activa. ¿Qué necesitas hacer hoy?",
            reply_markup=kb.main_menu(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    welcome_text = (
        f"👋 *¡Hola {user.first_name}! Bienvenido al bot VIP*\n\n"
        f"Para acceder al canal exclusivo de copy trading, necesitas un código de activación.\n\n"
        f"🔑 *¿Tienes un código?*\nSi ya tienes un código proporcionado por soporte, simplemente *pégalo aquí* y te daré acceso inmediato.\n\n"
        f"❓ *¿No tienes código?*\nContacta con el administrador para adquirir tu membresía.\n\n"
        f"✏️ *Escribe tu código VIP aquí* o usa el botón de abajo:"
    )
    keyboard = [[InlineKeyboardButton("🔑 Pegar mi código", callback_data="activate")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def activate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(
            "🔑 *Activar código VIP*\n\nPor favor, escribe el código que te proporcionó soporte.\n\n✏️ *Ejemplo:* `VIP-ABC123`\n\n_El código es sensible a mayúsculas, escríbelo exactamente como te lo dieron._",
            reply_markup=kb.cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🔑 *Perfecto, dime tu código VIP:*\n\nEscríbelo exactamente como te lo dio soporte.",
            reply_markup=kb.cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    return STATE_ACTIVATE

async def activate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    user = update.effective_user
    code = update.message.text.strip().upper()
    await update.message.chat.send_action(action="typing")
    await asyncio.sleep(0.5)
    try:
        row = await db.get_code(code)
    except Exception as e:
        logger.error(f"Error DB: {e}")
        await update.message.reply_text("❌ *Error interno*\n\nHubo un problema al verificar el código. Por favor, intenta de nuevo en unos segundos.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text("❌ *Código inválido*\n\nEl código que ingresaste no existe, ya fue usado o está desactivado.\n\n🔍 Verifica que lo escribiste correctamente o contacta a soporte.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    days = row["days"]
    sub = await db.get_subscription(user.id)
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
    await update.message.chat.send_action(action="typing")
    await asyncio.sleep(0.5)
    link = await add_to_channel(context.bot, user.id)
    success_text = f"✅ *¡Felicidades {user.first_name}!*\n\nTu código *{code}* ha sido activado correctamente.\n\n📅 *Días agregados:* {days}\n⏳ *Válido hasta:* {fmt_expiry(new_exp)}\n\n"
    if link:
        success_text += f"🔗 *Accede al canal VIP aquí:*\n{link}\n\n_El link es de un solo uso y expira en 5 minutos._"
    else:
        success_text += f"⚠️ *No pude generar el link automáticamente.*\nPor favor, contacta a soporte para que te agreguen al canal."
    success_text += f"\n\n✨ Ya puedes usar todas las funciones del bot y la calculadora VIP."
    await update.message.reply_text(success_text, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    await db.log_event("activate", user.id, f"code={code} days={days}")
    logger.info(f"✅ Usuario {user.id} activó {code} (+{days} días)")
    return ConversationHandler.END

async def renew_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🔄 *Renovar acceso*\n\n¿Tienes un código de renovación? Escríbelo aquí y sumaré días a tu membresía actual.\n\n✏️ *Escribe tu código:*", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_RENEW

async def renew_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip().upper()
    row = await db.get_code(code)
    if not row or row["used_count"] >= row["max_uses"]:
        await update.message.reply_text("❌ *Código inválido*\n\nEl código no existe o ya fue usado.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    sub = await db.get_subscription(user.id)
    if not sub:
        await update.message.reply_text("⚠️ *No tienes membresía activa*\n\nUsa la opción *Activar código* primero para obtener tu primer acceso.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    days = row["days"]
    current_exp = datetime.strptime(sub["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    new_exp = max(current_exp, utc_now()) + timedelta(days=days)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, days, code)
    await db.use_code(code)
    if row["used_count"] + 1 >= row["max_uses"]:
        await db.deactivate_code(code)
    await update.message.reply_text(f"✅ *¡Renovación exitosa!*\n\nSe agregaron *{days} días* a tu membresía.\n📅 Nueva fecha de vencimiento: `{fmt_expiry(new_exp)}`", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
    await db.log_event("renew", user.id, f"code={code} days={days}")
    return ConversationHandler.END

async def free_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user
    if await db.has_used_trial(user.id):
        await q.edit_message_text("⚠️ *Ya usaste tu prueba gratuita*\n\nCada usuario puede usar la prueba gratis solo una vez.\nAdquiere un código VIP para continuar.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return
    new_exp = utc_now() + timedelta(days=FREE_TRIAL_DAYS)
    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    await db.upsert_subscription(user.id, user.username or "", user.first_name, exp_str, FREE_TRIAL_DAYS, "FREE_TRIAL")
    await db.mark_trial_used(user.id)
    link = await add_to_channel(context.bot, user.id)
    reply_text = f"🎁 *¡Prueba gratuita activada!*\n\nDisfruta *{FREE_TRIAL_DAYS} días* de acceso VIP.\n📅 Vence: `{fmt_expiry(new_exp)}`\n\n"
    if link:
        reply_text += f"🔗 [Accede al canal aquí]({link})\n\n"
    reply_text += "_La prueba es por única vez. Aprovecha al máximo el contenido._"
    await q.edit_message_text(reply_text, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    await db.log_event("trial", user.id, f"days={FREE_TRIAL_DAYS}")

async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    user = q.from_user
    events = await db.get_user_history(user.id)
    if not events:
        await q.edit_message_text(f"📜 *Historial de {user.first_name}*\n\n_Aún no tienes actividad registrada._\n\nComienza activando un código o usando la prueba gratis.", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
        return
    txt = f"📜 *Historial de {user.first_name}*\n\n"
    for e in events[:10]:
        txt += f"• `{e['created_at'][:16]}` — {e['event']}\n"
    await q.edit_message_text(txt, reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)

async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context):
        return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🎟️ *Centro de Soporte*\n\n¿Tienes algún problema o consulta?\nCrea un ticket y te responderemos a la brevedad.\n\n_Tiempo de respuesta: 24-48h_", reply_markup=kb.support_menu(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# TICKETS - USUARIO
# ──────────────────────────────────────────────────────────────
async def ticket_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("✏️ *Nuevo ticket de soporte*\n\nPrimero, ¿cuál es el *asunto* de tu consulta?\n_(Ej: Problema con acceso, código no funciona, duda general)_", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_SUBJECT

async def ticket_subject_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ticket_subject"] = update.message.text.strip()[:100]
    await update.message.reply_text("💬 *Describe tu problema*\n\nCuéntanos con detalle qué sucede. Incluye toda la información que pueda ayudar a resolverlo más rápido.", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_MESSAGE

async def ticket_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subject = context.user_data.get("ticket_subject", "Sin asunto")
    content = update.message.text.strip()
    ticket_id = await db.create_ticket(user.id, user.username or "", user.first_name, subject)
    await db.add_ticket_message(ticket_id, user.id, content, is_admin=False)
    await db.log_event("ticket", user.id, f"id={ticket_id}")
    await update.message.reply_text(f"✅ *Ticket #{ticket_id:04d} creado*\n\n📌 Asunto: _{subject}_\n\nTe notificaremos cuando tengamos una respuesta. ¡Gracias por tu paciencia!", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(context.bot, aid, f"🎟️ *Nuevo ticket #{ticket_id:04d}*\n👤 {user.first_name} (`{user.id}`)\n📌 {subject}\n\n{content[:200]}...", reply_markup=kb.admin_ticket_actions(ticket_id, True))
    return ConversationHandler.END

async def ticket_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return
    q = update.callback_query
    await q.answer()
    tickets = await db.get_user_tickets(q.from_user.id)
    if not tickets:
        await q.edit_message_text("📭 No tienes tickets abiertos.", reply_markup=kb.main_menu())
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
    txt = f"🎟️ *Ticket #{tid:04d}*\n📌 {ticket['subject']}\n🔘 Estado: {'🟢 Abierto' if ticket['status']=='open' else '⚫ Cerrado'}\n\n"
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
    await q.edit_message_text(f"✍️ *Responder al ticket #{tid:04d}*\n\nEscribe tu mensaje:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_TICKET_REPLY_USER

async def ticket_reply_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tid = context.user_data.get("reply_ticket_id")
    if not tid:
        return ConversationHandler.END
    await db.add_ticket_message(tid, user.id, update.message.text.strip(), is_admin=False)
    await update.message.reply_text(f"✅ *Respuesta enviada al ticket #{tid:04d}*", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)
    admin_ids = await db.get_all_admin_ids()
    for aid in admin_ids:
        await notify_user(context.bot, aid, f"🔔 *Nueva respuesta en ticket #{tid:04d}*\n👤 {user.first_name}\n\n{update.message.text.strip()[:200]}", reply_markup=kb.admin_ticket_actions(tid, True))
    return ConversationHandler.END

async def ticket_close_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)
    await q.edit_message_text(f"✅ *Ticket #{tid:04d} cerrado*", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)

async def ticket_reopen_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)
    await q.edit_message_text(f"🔄 *Ticket #{tid:04d} reabierto*", reply_markup=kb.main_menu(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# ADMIN - TICKETS
# ──────────────────────────────────────────────────────────────
async def adm_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    open_c = len(await db.get_open_tickets())
    await q.edit_message_text(f"🎟️ *Gestión de Tickets*\n\n📂 Tickets abiertos: *{open_c}*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 Ver abiertos", callback_data="adm_tickets_open")],[InlineKeyboardButton("📋 Ver todos", callback_data="adm_tickets_all")],[InlineKeyboardButton("← Admin", callback_data="adm_panel")]]), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tickets = await db.get_open_tickets()
    if not tickets:
        await q.edit_message_text("✅ Sin tickets abiertos", reply_markup=kb.admin_back())
        return
    btns = [[InlineKeyboardButton(f"#{t['id']:04d} {t['subject'][:25]}", callback_data=f"adm_tview_{t['id']}")] for t in tickets[:10]]
    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])
    await q.edit_message_text("🟢 *Tickets abiertos*", reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def adm_tickets_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tickets = await db.get_all_tickets(20)
    btns = []
    for t in tickets:
        icon = "🟢" if t["status"] == "open" else "⚫"
        btns.append([InlineKeyboardButton(f"{icon} #{t['id']:04d} {t['subject'][:20]}", callback_data=f"adm_tview_{t['id']}")])
    btns.append([InlineKeyboardButton("← Admin", callback_data="adm_panel")])
    await q.edit_message_text("📋 *Todos los tickets*", reply_markup=InlineKeyboardMarkup(btns), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    ticket = await db.get_ticket(tid)
    if not ticket:
        await q.answer("❌ Ticket no encontrado", show_alert=True)
        return
    msgs = await db.get_ticket_messages(tid)
    txt = f"🎟️ *Ticket #{tid:04d}*\n👤 {ticket['first_name']} (`{ticket['user_id']}`)\n📌 {ticket['subject']}\n🔘 Estado: {'🟢 Abierto' if ticket['status']=='open' else '⚫ Cerrado'}\n\n"
    for m in msgs[-6:]:
        who = "🛡️ Admin" if m["is_admin"] else "👤 Usuario"
        txt += f"*{who}* `{m['sent_at'][:16]}`\n{m['message'][:200]}\n\n"
    await q.edit_message_text(txt[:4000], reply_markup=kb.admin_ticket_actions(tid, ticket["status"]=="open"), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    context.user_data["adm_reply_ticket"] = tid
    await q.edit_message_text(f"✍️ *Responder al ticket #{tid:04d}*\n\nEscribe tu respuesta:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_ADM_TICKET_REPLY

async def adm_ticket_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    tid = context.user_data.get("adm_reply_ticket")
    if not tid:
        return ConversationHandler.END
    ticket = await db.get_ticket(tid)
    await db.add_ticket_message(tid, admin.id, update.message.text.strip(), is_admin=True)
    await update.message.reply_text(f"✅ *Respuesta enviada al ticket #{tid:04d}*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    if ticket:
        await notify_user(context.bot, ticket["user_id"], f"🔔 *Nueva respuesta en tu ticket #{tid:04d}*\n\n{update.message.text.strip()[:500]}", reply_markup=kb.main_menu())
    return ConversationHandler.END

async def adm_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.close_ticket(tid)
    await q.edit_message_text(f"✅ *Ticket #{tid:04d} cerrado*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_ticket_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    await db.reopen_ticket(tid)
    await q.edit_message_text(f"🔄 *Ticket #{tid:04d} reabierto*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# ADMIN - GESTIÓN DE ADMINS
# ──────────────────────────────────────────────────────────────
async def adm_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🛡️ *Gestión de Administradores*\n\n"
        "Puedes agregar o quitar administradores.\n\n"
        "⚠️ *Nota:* El admin principal (ID original) no puede ser removido.",
        reply_markup=kb.admin_management_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Agregar administrador*\n\n"
        "Envía el *user_id* del usuario que quieres agregar como admin.\n\n"
        "Puedes obtener el ID enviando /id en el chat con el bot.\n\n"
        "✏️ *Ejemplo:* `123456789`",
        reply_markup=kb.cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return STATE_ADMIN_ADD

async def adm_add_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ *ID inválido*\n\nDebe ser un número.", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    
    if user_id == ADMIN_ID:
        await update.message.reply_text("⚠️ *El admin principal ya tiene permisos*\n\nNo es necesario agregarlo.", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    
    # Obtener info del usuario
    try:
        chat = await context.bot.get_chat(user_id)
        username = chat.username or ""
        first_name = chat.first_name or ""
    except TelegramError:
        username = ""
        first_name = f"Usuario_{user_id}"
    
    await db.add_admin(user_id, username, first_name, update.effective_user.id)
    await db.audit(update.effective_user.id, "add_admin", str(user_id), f"{first_name} @{username}")
    
    await update.message.reply_text(
        f"✅ *Administrador agregado*\n\n"
        f"👤 {first_name} (`{user_id}`)\n"
        f"Ahora tiene acceso al panel de administración.",
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Notificar al nuevo admin
    await notify_user(context.bot, user_id, 
        "🛡️ *Has sido agregado como administrador del bot VIP*\n\n"
        "Ya puedes usar el comando /admin para acceder al panel de control.\n\n"
        "_Si esto fue un error, contacta al administrador principal._",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END

async def adm_remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    
    admins = await db.list_admins()
    if not admins:
        await q.edit_message_text(
            "📭 *No hay administradores adicionales*\n\n"
            "Solo existe el admin principal.",
            reply_markup=kb.admin_back(),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    text = "➖ *Quitar administrador*\n\n"
    text += "Envía el *user_id* del admin que quieres remover:\n\n"
    text += "📋 *Admins actuales:*\n"
    for a in admins:
        text += f"• `{a['user_id']}` — {a['first_name'] or a['username'] or 'Sin nombre'}\n"
    text += "\n✏️ *Ejemplo:* `123456789`"
    
    await q.edit_message_text(text, reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_ADMIN_REMOVE

async def adm_remove_admin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ *ID inválido*\n\nDebe ser un número.", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    
    if user_id == ADMIN_ID:
        await update.message.reply_text("⚠️ *No puedes remover al admin principal*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    
    # Verificar si existe
    admins = await db.get_all_admin_ids()
    if user_id not in admins:
        await update.message.reply_text(f"❌ *El usuario `{user_id}` no es administrador*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    
    await db.remove_admin(user_id)
    await db.audit(update.effective_user.id, "remove_admin", str(user_id), "")
    
    await update.message.reply_text(
        f"✅ *Administrador removido*\n\n"
        f"Usuario `{user_id}` ya no tiene permisos de admin.",
        reply_markup=kb.admin_panel(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Notificar al removido
    await notify_user(context.bot, user_id,
        "⚠️ *Has sido removido como administrador del bot VIP*\n\n"
        "Ya no tienes acceso al panel de administración.\n\n"
        "_Si crees que esto fue un error, contacta al administrador principal._",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END

async def adm_list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    
    admins = await db.list_admins()
    text = "🛡️ *Lista de Administradores*\n\n"
    text += f"👑 *Admin principal:* `{ADMIN_ID}`\n\n"
    
    if admins:
        text += "👥 *Admins adicionales:*\n"
        for a in admins:
            name = a['first_name'] or a['username'] or 'Sin nombre'
            text += f"• `{a['user_id']}` — {name}\n"
    else:
        text += "📭 *No hay admins adicionales*"
    
    await q.edit_message_text(text, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# ADMIN - PANEL PRINCIPAL
# ──────────────────────────────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 No tienes permisos para usar este comando.")
        return
    await update.message.reply_text("🛡️ *Panel de Administración*\n\nBienvenido al panel de control. Selecciona una opción:", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🛡️ *Panel de Administración*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)

async def adm_gen_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔑 *Generar código VIP*\n\nSelecciona la duración del código:",
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
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data.split("_")[-1]
    if data == "custom":
        await q.edit_message_text("✏️ *Código personalizado*\n\nFormato: `días usos [nota]`\nEjemplo: `30 5 Clientes junio`", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return STATE_GEN_CODE
    days = int(data)
    code = await unique_code()
    await db.create_code(code, days, 1, created_by=q.from_user.id)
    await db.audit(q.from_user.id, "gen_code", code, f"days={days}")
    await q.edit_message_text(f"✅ *Código generado*\n\n🔑 `{code}`\n📅 Días: *{days}*\n👤 Usos: *1*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def adm_gen_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    parts = update.message.text.strip().split()
    try:
        days = int(parts[0])
        uses = int(parts[1]) if len(parts) > 1 else 1
        note = " ".join(parts[2:]) if len(parts) > 2 else ""
    except (ValueError, IndexError):
        await update.message.reply_text("❌ *Formato inválido*\n\nUsa: `días usos [nota]`\nEjemplo: `30 5 Clientes`", parse_mode=ParseMode.MARKDOWN)
        return STATE_GEN_CODE
    code = await unique_code()
    await db.create_code(code, days, uses, note, created_by=update.effective_user.id)
    await db.audit(update.effective_user.id, "gen_code", code, f"days={days} uses={uses}")
    await update.message.reply_text(f"✅ *Código generado*\n\n🔑 `{code}`\n📅 Días: *{days}*\n👤 Usos: *{uses}*\n📝 Nota: {note if note else 'Sin nota'}", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

async def adm_list_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    query = update.callback_query
    await query.answer()
    data = query.data
    page = 1
    if data.startswith("adm_list_codes_page_"):
        try:
            page = int(data.split("_")[-1])
        except ValueError:
            page = 1
    now = time.time()
    if _admin_cache["codes"]["data"] and (now - _admin_cache["codes"]["timestamp"]) < CACHE_DURATION:
        codes = _admin_cache["codes"]["data"]
    else:
        codes = await db.get_active_codes()
        _admin_cache["codes"] = {"data": codes, "timestamp": now}
    if not codes:
        await query.edit_message_text("📭 *Sin códigos activos*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
        return
    items_per_page = 10
    total_pages = (len(codes) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_codes = codes[start:end]
    txt = f"🔑 *Códigos activos* (página {page}/{total_pages})\n\n"
    for c in page_codes:
        remaining = c['max_uses'] - c['used_count']
        txt += f"`{c['code']}` — {c['days']}d — {remaining}/{c['max_uses']} usos\n"
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ Anterior", callback_data=f"adm_list_codes_page_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Siguiente ▶", callback_data=f"adm_list_codes_page_{page+1}"))
    reply_markup = InlineKeyboardMarkup([buttons, [InlineKeyboardButton("« Panel admin", callback_data="adm_panel")]])
    await query.edit_message_text(txt, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def adm_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    query = update.callback_query
    await query.answer()
    data = query.data
    page = 1
    if data.startswith("adm_members_page_"):
        try:
            page = int(data.split("_")[-1])
        except ValueError:
            page = 1
    now = time.time()
    if _admin_cache["members"]["data"] and (now - _admin_cache["members"]["timestamp"]) < CACHE_DURATION:
        members = _admin_cache["members"]["data"]
    else:
        members = await db.get_all_subscriptions()
        _admin_cache["members"] = {"data": members, "timestamp": now}
    if not members:
        await query.edit_message_text("👥 *Sin miembros registrados*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
        return
    items_per_page = 10
    total_pages = (len(members) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_members = members[start:end]
    txt = f"👥 *Miembros activos* (página {page}/{total_pages})\n\n"
    for m in page_members:
        d = days_left(m["expiry"])
        emoji = "🟢" if d > 3 else ("🟡" if d > 1 else "🔴")
        txt += f"{emoji} {m['first_name']} (`{m['user_id']}`) — {d}d\n"
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ Anterior", callback_data=f"adm_members_page_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Siguiente ▶", callback_data=f"adm_members_page_{page+1}"))
    reply_markup = InlineKeyboardMarkup([buttons, [InlineKeyboardButton("« Panel admin", callback_data="adm_panel")]])
    await query.edit_message_text(txt, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    s = await db.get_stats_summary()
    txt = f"📊 *Estadísticas*\n\n👥 Total miembros: *{s['total']}*\n✅ Activos: *{s['active']}*\n🆕 Nuevos hoy: *{s['new_today']}*\n⚠️ Vencen en 3d: *{s['expiring_3d']}*\n🔑 Códigos activos: *{s['codes']}*\n🎟️ Tickets abiertos: *{s['tickets_open']}*\n🚫 Bloqueados: *{s['banned']}*\n🎁 Pruebas usadas: *{s['trials']}*\n👥 Admins: *{s['admins']}*"
    await q.edit_message_text(txt, reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📢 *Broadcast*\n\n¿A quién quieres enviar el mensaje?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Todos los miembros", callback_data="adm_bc_all")],
            [InlineKeyboardButton("✅ Solo activos", callback_data="adm_bc_active")],
            [InlineKeyboardButton("⚠️ Por vencer (3d)", callback_data="adm_bc_expiring")],
            [InlineKeyboardButton("← Admin", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def adm_broadcast_segment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    seg = q.data.replace("adm_bc_", "")
    BROADCAST_FILTER["segment"] = seg
    await q.edit_message_text(f"✍️ *Escribe el mensaje*\n\nSegmento seleccionado: *{seg}*\n\nRedacta el mensaje que quieres enviar:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_BROADCAST_MSG

async def adm_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seg = BROADCAST_FILTER.get("segment", "all")
    context.user_data["bc_message"] = update.message.text.strip()
    await update.message.reply_text(
        f"📢 *Vista previa*\n\nSegmento: *{seg}*\n\n{context.user_data['bc_message']}\n\n¿Enviar ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enviar", callback_data="adm_broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="adm_panel")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def adm_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("📤 Enviando mensajes...")
    seg = BROADCAST_FILTER.get("segment", "all")
    txt = context.user_data.get("bc_message", "")
    if not txt:
        await q.edit_message_text("❌ Error: mensaje vacío", reply_markup=kb.admin_back())
        return
    if seg == "active":
        members = [m for m in await db.get_all_subscriptions() if days_left(m["expiry"]) > 0]
    elif seg == "expiring":
        members = await db.get_expiring_soon(72)
    else:
        members = await db.get_all_subscriptions()
    ok, fail = 0, 0
    await q.edit_message_text(f"📤 Enviando a {len(members)} usuarios...")
    for m in members:
        try:
            await context.bot.send_message(m["user_id"], txt, parse_mode=ParseMode.MARKDOWN)
            ok += 1
        except TelegramError:
            fail += 1
        await asyncio.sleep(0.05)
    await db.log_broadcast(txt, seg, ok, fail)
    await q.edit_message_text(f"✅ *Broadcast completado*\n\n📨 Enviados: *{ok}*\n❌ Fallidos: *{fail}*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# ADMIN - KICK MEMBER (EXPULSAR MIEMBRO)
# ──────────────────────────────────────────────────────────────
async def adm_kick_member_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("✏️ *Expulsar miembro*\n\nEscribe el *user_id* del usuario que quieres expulsar del canal:", reply_markup=kb.cancel_keyboard(), parse_mode=ParseMode.MARKDOWN)
    return STATE_KICK_MEMBER

async def adm_kick_member_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return ConversationHandler.END
    try:
        user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ ID inválido. Debe ser un número.")
        return ConversationHandler.END
    try:
        await context.bot.ban_chat_member(CHANNEL_ID, user_id)
        await context.bot.unban_chat_member(CHANNEL_ID, user_id)
        await update.message.reply_text(f"✅ Usuario `{user_id}` expulsado del canal.")
        await db.audit(update.effective_user.id, "kick_member", str(user_id))
    except Exception as e:
        await update.message.reply_text(f"❌ Error al expulsar: {e}")
    await update.message.reply_text("🛡️ *Panel de Administración*", reply_markup=kb.admin_panel(), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

# ──────────────────────────────────────────────────────────────
# ADMIN - MANTENIMIENTO (limpiar vencidos, exportar, backup)
# ──────────────────────────────────────────────────────────────
async def adm_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🔧 *Mantenimiento*", reply_markup=kb.admin_maintenance_menu(), parse_mode=ParseMode.MARKDOWN)

async def adm_clean_expired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("🧹 Limpiando...")
    expired = await db.get_expired_members()
    for m in expired:
        await kick_from_channel(context.bot, m["user_id"])
        await db.delete_subscription(m["user_id"])
        await asyncio.sleep(0.05)
    await q.edit_message_text(f"✅ *Limpieza completada*\n\nSe eliminaron *{len(expired)}* miembros vencidos.", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("📤 Generando CSV...")
    csv_data = await db.export_members_csv()
    await context.bot.send_document(
        q.from_user.id,
        document=io.BytesIO(csv_data.encode()),
        filename=f"miembros_{datetime.now().strftime('%Y%m%d')}.csv",
        caption="📊 Exportación de miembros"
    )
    await q.edit_message_text("✅ *CSV enviado*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

async def adm_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    q = update.callback_query
    await q.answer("💾 Generando backup...")
    try:
        with open(DB_PATH, "rb") as f:
            await context.bot.send_document(q.from_user.id, document=f, filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db", caption="🗄️ Backup de base de datos")
        await q.edit_message_text("✅ *Backup enviado*", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await q.edit_message_text(f"❌ Error: {str(e)}", reply_markup=kb.admin_back(), parse_mode=ParseMode.MARKDOWN)

# ──────────────────────────────────────────────────────────────
# COMANDOS DIRECTOS (ADMIN)
# ──────────────────────────────────────────────────────────────
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
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
    if not await is_admin(update.effective_user.id): return
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
    if not await is_admin(update.effective_user.id): return
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

# ──────────────────────────────────────────────────────────────
# AUTO-RESPUESTA
# ──────────────────────────────────────────────────────────────
async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update, context): return
    user = update.effective_user
    text = (update.message.text or "").lower()
    sub = await db.get_subscription(user.id)
    if not sub or days_left(sub["expiry"]) <= 0:
        await update.message.reply_text(
            f"👋 *Hola {user.first_name}*\n\nPara usar el bot, primero necesitas activar un código VIP.\n\n🔑 Por favor, escribe tu código aquí:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔑 Activar código", callback_data="activate")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
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
    await update.message.reply_text(
        f"💬 *Hola {user.first_name}*\n\nUsa los botones del menú para acceder a las funciones del bot.",
        reply_markup=kb.main_menu(),
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
        await asyncio.sleep(0.05)
    if expired:
        logger.info(f"🧹 Limpieza: {len(expired)} miembros eliminados")

async def job_warn_expiring(context: ContextTypes.DEFAULT_TYPE):
    for hours in [72, 24, 1]:
        members = await db.get_expiring_soon(hours)
        for m in members:
            d_left = days_left(m["expiry"])
            if hours == 72:
                text = f"⚠️ *Tu membresía vence en 3 días*\n\n📅 Vencimiento: `{m['expiry'][:16]}`\n⏳ Días restantes: *{d_left}*\n\nRenueva pronto para no perder acceso."
            elif hours == 24:
                text = f"🔔 *Tu membresía vence MAÑANA*\n\n📅 Vencimiento: `{m['expiry'][:16]}`\n⏳ Días restantes: *{d_left}*\n\n¡Renueva hoy mismo!"
            else:
                text = f"🚨 *¡ÚLTIMAS HORAS!*\n\nTu membresía vence en *menos de 1 hora*.\nRenueva ahora para no perder el acceso."
            await notify_user(context.bot, m["user_id"], text, reply_markup=kb.main_menu())

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    stats = await db.get_stats_summary()
    admin_ids = await db.get_all_admin_ids()
    text = f"📊 *Resumen diario*\n\n👥 Activos: *{stats['active']}*\n📆 Nuevos hoy: *{stats['new_today']}*\n⚠️ Vencen pronto: *{stats['expiring_3d']}*\n🎟️ Tickets abiertos: *{stats['tickets_open']}*\n👥 Admins: *{stats['admins']}*"
    for aid in admin_ids:
        await notify_user(context.bot, aid, text)

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    async def _run():
        await db.init_db()
        if not BOT_TOKEN:
            logger.critical("BOT_TOKEN no configurado")
            return
        await start_api_server()
        app = Application.builder().token(BOT_TOKEN).build()

        # Conversaciones
        convs = [
            ConversationHandler(
                entry_points=[CallbackQueryHandler(activate_start, pattern="^activate$"), MessageHandler(filters.TEXT & ~filters.COMMAND, activate_start)],
                states={STATE_ACTIVATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, activate_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(renew_start, pattern="^renew$")],
                states={STATE_RENEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, renew_code)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_gen_code_menu, pattern="^adm_gen_code$")],
                states={STATE_GEN_CODE: [CallbackQueryHandler(adm_gen_code_quick, pattern="^adm_quick_"), MessageHandler(filters.TEXT & ~filters.COMMAND, adm_gen_code_input)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_broadcast_segment, pattern="^adm_bc_")],
                states={STATE_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_preview)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_new_start, pattern="^ticket_new$")],
                states={STATE_TICKET_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_subject_received)], STATE_TICKET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_message_received)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(ticket_reply_start, pattern="^ticket_reply_")],
                states={STATE_TICKET_REPLY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_reply_user_message)]},
                fallbacks=[CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_ticket_reply_start, pattern="^adm_ticket_reply_")],
                states={STATE_ADM_TICKET_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_ticket_reply_message)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_kick_member_start, pattern="^adm_kick_member$")],
                states={STATE_KICK_MEMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_kick_member_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            # Admin management conversations
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_add_admin_start, pattern="^adm_add_admin$")],
                states={STATE_ADMIN_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
            ConversationHandler(
                entry_points=[CallbackQueryHandler(adm_remove_admin_start, pattern="^adm_remove_admin$")],
                states={STATE_ADMIN_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_remove_admin_received)]},
                fallbacks=[CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$")],
                conversation_timeout=300
            ),
        ]
        for conv in convs:
            app.add_handler(conv)

        # Comandos
        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("admin", admin_command))
        app.add_handler(CommandHandler("ban", ban_command))
        app.add_handler(CommandHandler("unban", unban_command))
        app.add_handler(CommandHandler("adddays", adddays_command))

        # Callbacks de usuario
        app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
        app.add_handler(CallbackQueryHandler(free_trial_callback, pattern="^free_trial$"))
        app.add_handler(CallbackQueryHandler(history_callback, pattern="^history$"))
        app.add_handler(CallbackQueryHandler(support_callback, pattern="^support$"))
        app.add_handler(CallbackQueryHandler(ticket_list_callback, pattern="^ticket_list$"))
        app.add_handler(CallbackQueryHandler(ticket_view_callback, pattern="^ticket_view_"))
        app.add_handler(CallbackQueryHandler(ticket_close_user, pattern="^ticket_close_"))
        app.add_handler(CallbackQueryHandler(ticket_reopen_user, pattern="^ticket_reopen_"))

        # Callbacks de admin
        app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^adm_panel$"))
        app.add_handler(CallbackQueryHandler(adm_list_codes, pattern="^adm_list_codes$"))
        app.add_handler(CallbackQueryHandler(adm_list_codes, pattern="^adm_list_codes_page_\\d+$"))
        app.add_handler(CallbackQueryHandler(adm_members, pattern="^adm_members$"))
        app.add_handler(CallbackQueryHandler(adm_members, pattern="^adm_members_page_\\d+$"))
        app.add_handler(CallbackQueryHandler(adm_stats, pattern="^adm_stats$"))
        app.add_handler(CallbackQueryHandler(adm_broadcast, pattern="^adm_broadcast$"))
        app.add_handler(CallbackQueryHandler(adm_broadcast_confirm, pattern="^adm_broadcast_confirm$"))
        app.add_handler(CallbackQueryHandler(adm_tickets, pattern="^adm_tickets$"))
        app.add_handler(CallbackQueryHandler(adm_tickets_open, pattern="^adm_tickets_open$"))
        app.add_handler(CallbackQueryHandler(adm_tickets_all, pattern="^adm_tickets_all$"))
        app.add_handler(CallbackQueryHandler(adm_ticket_view, pattern="^adm_tview_"))
        app.add_handler(CallbackQueryHandler(adm_ticket_close, pattern="^adm_ticket_close_"))
        app.add_handler(CallbackQueryHandler(adm_ticket_reopen, pattern="^adm_ticket_reopen_"))
        app.add_handler(CallbackQueryHandler(adm_maintenance, pattern="^adm_maintenance$"))
        app.add_handler(CallbackQueryHandler(adm_clean_expired, pattern="^adm_clean_expired$"))
        app.add_handler(CallbackQueryHandler(adm_export_csv, pattern="^adm_export_csv$"))
        app.add_handler(CallbackQueryHandler(adm_backup, pattern="^adm_backup$"))
        # Admin management callbacks
        app.add_handler(CallbackQueryHandler(adm_manage_admins, pattern="^adm_manage_admins$"))
        app.add_handler(CallbackQueryHandler(adm_list_admins, pattern="^adm_list_admins$"))

        # Auto-respuesta
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply))

        # Jobs (sin calendar ni news)
        jq = app.job_queue
        jq.run_repeating(job_clean_expired, interval=3600, first=60)
        jq.run_repeating(job_warn_expiring, interval=43200, first=120)
        jq.run_daily(job_daily_summary, time=datetime.strptime("08:00", "%H:%M").time())

        logger.info(f"🚀 Bot iniciado | Canal: {CHANNEL_ID}")

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
