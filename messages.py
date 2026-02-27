"""
messages.py — VIP Bot · Textos premium
"""

from datetime import datetime, timezone

SEP   = "━━━━━━━━━━━━━━━━━━━━━━━━"
SEP_S = "──────────────────────"


# ══════════════════════════════════════════════════════════════
# USUARIO
# ══════════════════════════════════════════════════════════════

def welcome(first_name: str) -> str:
    return (
        f"💎 *Bienvenido, {first_name}*\n"
        f"{SEP}\n\n"
        f"Accede al canal VIP exclusivo de *Copy Trading*\n"
        f"activando tu código o renovando tu membresía.\n\n"
        f"📲 Usa *Calculadora VIP* para ver tu tarjeta\n"
        f"con el tiempo restante y la calculadora de lotaje.\n\n"
        f"Selecciona una opción:"
    )

def already_banned() -> str:
    return (
        f"🚫 *Acceso denegado*\n"
        f"{SEP}\n\n"
        f"Tu cuenta ha sido suspendida.\n"
        f"Contacta a soporte si crees que es un error."
    )

def no_membership() -> str:
    return (
        f"💎 *Sin membresía activa*\n"
        f"{SEP}\n\n"
        f"No tienes un acceso VIP activo.\n\n"
        f"🔑 Activa un código VIP\n"
        f"🎁 O prueba *30 días gratis*"
    )

def activation_success(first_name: str, days: int, expiry: str) -> str:
    return (
        f"✅ *¡Acceso activado, {first_name}!*\n"
        f"{SEP}\n\n"
        f"📅 Vence: `{expiry}`\n"
        f"⏳ Días incluidos: *{days}*\n\n"
        f"Ya tienes acceso al canal exclusivo. 💎"
    )

def renewal_success(days: int, expiry: str) -> str:
    return (
        f"✅ *Acceso renovado*\n"
        f"{SEP}\n\n"
        f"Se sumaron *{days} días* a tu membresía.\n"
        f"📅 Nuevo vencimiento: `{expiry}`"
    )

def free_trial_success(expiry: str) -> str:
    return (
        f"🎁 *¡Prueba gratuita activada!*\n"
        f"{SEP}\n\n"
        f"Disfruta *30 días* de acceso VIP.\n"
        f"📅 Vence: `{expiry}`\n\n"
        f"_La prueba gratuita es por única vez._"
    )

def free_trial_already_used() -> str:
    return (
        f"⚠️ *Prueba ya utilizada*\n"
        f"{SEP}\n\n"
        f"Ya usaste tu prueba gratuita anteriormente.\n"
        f"Activa un código VIP para continuar."
    )

def code_not_found() -> str:
    return (
        f"❌ *Código inválido*\n"
        f"{SEP}\n\n"
        f"El código no existe, ya fue usado,\n"
        f"fue desactivado o expiró. Verifica e intenta de nuevo."
    )

def expiry_warning(days_left: int) -> str:
    if days_left <= 1:
        icon, msg = "🔴", "¡Tu acceso VIP vence en menos de *24 horas*!"
    else:
        icon, msg = "🟡", f"Tu acceso VIP vence en *{days_left} días*."
    return (
        f"{icon} *Aviso de vencimiento*\n"
        f"{SEP}\n\n"
        f"{msg}\n\n"
        f"Renueva tu membresía para mantener el acceso."
    )

def expired_notification() -> str:
    return (
        f"⏰ *Tu membresía ha vencido*\n"
        f"{SEP}\n\n"
        f"Has sido removido del canal VIP.\n"
        f"Activa un nuevo código para recuperar el acceso."
    )

def history_header(first_name: str) -> str:
    return f"📜 *Historial de {first_name}*\n{SEP}\n\n"

def history_item(event: str, data: str, date: str) -> str:
    icons = {
        "activate": "🔑", "renew": "🔄", "trial": "🎁",
        "expired": "⏰",  "kicked": "🚪", "banned": "🚫",
        "ticket": "🎟️",
    }
    icon = icons.get(event.split("_")[0], "•")
    return f"{icon} `{date}` — {event}\n   _{data}_\n"


# ══════════════════════════════════════════════════════════════
# SOPORTE / TICKETS
# ══════════════════════════════════════════════════════════════

def support_menu_text() -> str:
    return (
        f"🎟️ *Centro de Soporte*\n"
        f"{SEP}\n\n"
        f"¿Tienes algún problema o consulta?\n"
        f"Crea un ticket y te responderemos a la brevedad.\n\n"
        f"_Tiempo de respuesta estimado: 24h_"
    )

def ticket_ask_subject() -> str:
    return (
        f"✏️ *Nuevo ticket*\n"
        f"{SEP}\n\n"
        f"Escribe el *asunto* de tu consulta\n"
        f"_(máx. 100 caracteres)_:"
    )

def ticket_ask_message() -> str:
    return (
        f"💬 *Describe tu problema*\n"
        f"{SEP}\n\n"
        f"Escribe tu mensaje con todos los detalles:"
    )

def ticket_created(ticket_id: int, subject: str) -> str:
    return (
        f"✅ *Ticket #{ticket_id:04d} creado*\n"
        f"{SEP}\n\n"
        f"📌 Asunto: _{subject}_\n\n"
        f"Te notificaremos cuando tengamos una respuesta. 💬"
    )

def ticket_new_reply_user(ticket_id: int, admin_msg: str) -> str:
    return (
        f"💬 *Respuesta a tu ticket #{ticket_id:04d}*\n"
        f"{SEP}\n\n"
        f"🛡️ *Soporte:*\n{admin_msg}\n\n"
        f"_Responde desde_ 🎟️ _Soporte → Mis tickets_"
    )


# ══════════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════════

def admin_code_created(code: str, days: int, uses: int, note: str) -> str:
    txt = (
        f"✅ *Código generado*\n"
        f"{SEP}\n\n"
        f"🔑 Código: `{code}`\n"
        f"📅 Días: *{days}*\n"
        f"🔁 Usos: *{uses}*\n"
        f"📝 Nota: _{note or 'Sin nota'}_"
    )
    return txt

def admin_adddays_success(user_id: int, days: int, new_expiry: str) -> str:
    return (
        f"✅ *Días añadidos*\n"
        f"{SEP}\n\n"
        f"Usuario: `{user_id}`\n"
        f"Días añadidos: *+{days}*\n"
        f"Nuevo vencimiento: `{new_expiry}`"
    )

def admin_ban_success(user_id: int) -> str:
    return f"🚫 Usuario `{user_id}` baneado correctamente."

def admin_unban_success(user_id: int) -> str:
    return f"✅ Usuario `{user_id}` desbaneado correctamente."

def daily_summary(stats: dict) -> str:
    return (
        f"☀️ *Resumen diario · VIP Bot*\n"
        f"{SEP}\n\n"
        f"👥 Miembros activos: *{stats['active']}*\n"
        f"🔴 Vencen en ≤3 días: *{stats['expiring_3d']}*\n"
        f"📆 Nuevos hoy: *{stats['new_today']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"🚫 Baneados: *{stats['banned']}*\n\n"
        f"_VIP Bot · {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_"
    )
