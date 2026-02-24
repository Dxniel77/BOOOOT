"""
messages.py — Todos los textos del bot (personaliza aquí)
"""
from datetime import datetime


def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso


def progress_bar(expires_at: str, total_days: int = 30) -> str:
    try:
        now    = datetime.now()
        expiry = datetime.fromisoformat(expires_at)
        remaining = (expiry - now).total_seconds()
        total     = total_days * 86400
        pct       = max(0.0, min(1.0, remaining / total))
        filled    = int(pct * 10)
        bar       = "█" * filled + "░" * (10 - filled)
        return f"[{bar}] {int(pct*100)}%"
    except Exception:
        return "[██████████] ?"


WELCOME = (
    "👋 *¡Bienvenido al bot de suscripción!*\n\n"
    "Usa los botones de abajo para gestionar tu acceso."
)

NO_SUBSCRIPTION = (
    "❌ *No tienes una suscripción activa.*\n\n"
    "Usa *🔑 Activar código* para acceder al canal."
)

ENTER_CODE = "✏️ Escribe tu código de activación:"

ENTER_CODE_RENEW = "🔄 Escribe el código para renovar tu suscripción:"

CODE_NOT_FOUND = "❌ Código inválido o agotado. Verifica e inténtalo de nuevo."

CODE_SUCCESS = (
    "✅ *¡Código activado correctamente!*\n\n"
    "Se te han añadido *{days} días* de acceso.\n"
    "Tu suscripción vence el: `{expires_at}`"
)

CODE_RENEWED = (
    "🔄 *¡Suscripción renovada!*\n\n"
    "Se añadieron *{days} días* a tu acceso.\n"
    "Nueva fecha de vencimiento: `{expires_at}`"
)

def subscription_status(sub: dict) -> str:
    now    = datetime.now()
    expiry = datetime.fromisoformat(sub["expires_at"])
    days_left = (expiry - now).days
    status = "✅ Activa" if expiry > now else "❌ Vencida"
    bar    = progress_bar(sub["expires_at"])
    return (
        f"📊 *Mi suscripción*\n\n"
        f"Estado: {status}\n"
        f"Vence: `{fmt_date(sub['expires_at'])}`\n"
        f"Días restantes: *{max(0, days_left)}*\n\n"
        f"{bar}"
    )

CONTACT_ADMIN = "📞 Contacta al administrador: @adminusername"

ADMIN_WELCOME = "🛡️ *Panel de Administración*\n\nSelecciona una acción:"

def admin_gen_code_prompt():
    return (
        "🔑 *Generar código nuevo*\n\n"
        "Escribe en formato:\n"
        "`CODIGO DIAS USOS`\n\n"
        "Ejemplo: `VIP30 30 5`\n"
        "_(crea el código VIP30 por 30 días con 5 usos)_"
    )

def admin_code_created(code: str, days: int, max_uses: int) -> str:
    return (
        f"✅ *Código creado:*\n\n"
        f"Código: `{code}`\n"
        f"Días: *{days}*\n"
        f"Usos máximos: *{max_uses}*"
    )

ADMIN_CODE_EXISTS = "⚠️ Ese código ya existe. Usa otro nombre."
ADMIN_CODE_INVALID = "❌ Formato inválido. Usa: `CODIGO DIAS USOS`\nEjemplo: `VIP30 30 1`"

def admin_list_codes(codes: list) -> str:
    if not codes:
        return "📋 No hay códigos activos."
    lines = ["📋 *Códigos activos:*\n"]
    for c in codes:
        lines.append(
            f"• `{c['code']}` — {c['days']}d | "
            f"{c['used_count']}/{c['max_uses']} usos"
        )
    return "\n".join(lines)

def admin_stats_msg(stats: dict) -> str:
    return (
        f"📊 *Estadísticas*\n\n"
        f"👥 Suscriptores totales: *{stats.get('total_subs', 0)}*\n"
        f"✅ Activos: *{stats.get('active_subs', 0)}*\n"
        f"⚠️ Vencen en 3 días: *{stats.get('expiring_soon', 0)}*\n\n"
        f"🔑 Códigos activos: *{stats.get('active_codes', 0)}* / "
        f"{stats.get('total_codes', 0)} total"
    )

ADMIN_ENTER_DEACTIVATE = "🔴 Escribe el código que deseas desactivar:"

def admin_confirm_deactivate(code: str) -> str:
    return f"⚠️ ¿Confirmas desactivar el código `{code}`?"

def admin_deactivated(code: str) -> str:
    return f"✅ Código `{code}` desactivado correctamente."

def admin_new_activation(user_id: int, username: str, full_name: str, days: int) -> str:
    uname = f"@{username}" if username else full_name
    return (
        f"🔔 *Nueva activación*\n\n"
        f"Usuario: {uname} (`{user_id}`)\n"
        f"Días añadidos: *{days}*"
    )

def warn_expiring(days_left: int) -> str:
    return (
        f"⚠️ *Tu suscripción vence en {days_left} días.*\n\n"
        "Renueva con el botón 🔄 Renovar para no perder el acceso."
    )

SUBSCRIPTION_EXPIRED = (
    "😔 Tu suscripción ha vencido y fuiste removido del canal.\n\n"
    "Usa *🔑 Activar código* para volver a acceder."
)

CANCEL = "❌ Acción cancelada."
OPERATION_TIMEOUT = "⏰ Tiempo de espera agotado. Vuelve al menú e inténtalo de nuevo."
