"""
messages.py — VIP Bot · Textos premium
"""

from datetime import datetime, timezone

SEP   = "━━━━━━━━━━━━━━━━━━━━━━━━"
SEP_S = "──────────────────────"

def welcome(first_name: str) -> str:
    return f"💎 *Bienvenido, {first_name}*\n{SEP}\n\nAccede al canal VIP exclusivo de *Copy Trading*\nactivando tu código o renovando tu membresía.\n\n📲 Usa *Calculadora VIP* para ver tu tarjeta\ncon el tiempo restante y la calculadora de lotaje.\n\nSelecciona una opción:"

def already_banned() -> str:
    return f"🚫 *Acceso denegado*\n{SEP}\n\nTu cuenta ha sido suspendida.\nContacta a soporte si crees que es un error."

def activation_success(first_name: str, days: int, expiry: str) -> str:
    return f"✅ *¡Acceso activado, {first_name}!*\n{SEP}\n\n📅 Vence: `{expiry}`\n⏳ Días incluidos: *{days}*\n\nYa tienes acceso al canal exclusivo. 💎"

def renewal_success(days: int, expiry: str) -> str:
    return f"✅ *Acceso renovado*\n{SEP}\n\nSe sumaron *{days} días* a tu membresía.\n📅 Nuevo vencimiento: `{expiry}`"

def free_trial_success(expiry: str) -> str:
    return f"🎁 *¡Prueba gratuita activada!*\n{SEP}\n\nDisfruta *30 días* de acceso VIP.\n📅 Vence: `{expiry}`\n\n_La prueba gratuita es por única vez._"

def free_trial_already_used() -> str:
    return f"⚠️ *Prueba ya utilizada*\n{SEP}\n\nYa usaste tu prueba gratuita anteriormente.\nActiva un código VIP para continuar."

def code_not_found() -> str:
    return f"❌ *Código inválido*\n{SEP}\n\nEl código no existe, ya fue usado,\nfue desactivado o expiró. Verifica e intenta de nuevo."

def expired_notification() -> str:
    return f"⏰ *Tu membresía ha vencido*\n{SEP}\n\nHas sido removido del canal VIP.\nActiva un nuevo código para recuperar el acceso."

def daily_summary(stats: dict) -> str:
    return f"☀️ *Resumen diario · VIP Bot*\n{SEP}\n\n👥 Miembros activos: *{stats['active']}*\n🔴 Vencen en ≤3 días: *{stats['expiring_3d']}*\n📆 Nuevos hoy: *{stats['new_today']}*\n🎟️ Tickets abiertos: *{stats['tickets_open']}*\n🚫 Baneados: *{stats['banned']}*\n\n_VIP Bot · {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_"
