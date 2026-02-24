"""
messages.py — Todos los textos del bot.
Edita aquí sin tocar lógica.
"""
from datetime import datetime, timezone


def fmt_date(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d/%m/%Y %H:%M UTC")


def days_left(iso: str) -> int:
    dt = datetime.fromisoformat(iso)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (dt - datetime.now(timezone.utc)).days)


def progress_bar(days: int, max_days: int = 30, width: int = 15) -> str:
    filled = min(width, int((days / max(max_days, 1)) * width))
    empty  = width - filled
    color  = "🟩" if days > 7 else "🟨" if days > 3 else "🟥"
    return color * filled + "⬜" * empty


# ── Usuario ───────────────────────────────────────────────────────────────────

def welcome(name: str) -> str:
    return (
        f"👋 *¡Hola, {name}!*\n\n"
        "Bienvenido al acceso exclusivo.\n"
        "Usa los botones de abajo para gestionar tu suscripción 👇"
    )


def menu_user_no_sub() -> str:
    return (
        "📋 *Menú principal*\n\n"
        "No tienes una suscripción activa.\n"
        "Pulsa *\"🔑 Activar código\"* para comenzar."
    )


def menu_user_active(expires_at: str) -> str:
    dl  = days_left(expires_at)
    bar = progress_bar(dl)
    em  = "🟢" if dl > 7 else "🟡" if dl > 3 else "🔴"
    return (
        f"📋 *Tu suscripción*\n\n"
        f"{em} Estado: *Activa*\n"
        f"📅 Vence: `{fmt_date(expires_at)}`\n"
        f"⏳ Quedan: *{dl} día{'s' if dl != 1 else ''}*\n\n"
        f"`{bar}` {dl}d"
    )


def ask_for_code(action: str) -> str:
    verb = "activar" if action == "activate" else "renovar"
    return (
        f"✏️ Escribe tu código de {verb}:\n\n"
        "_Solo escribe el código, sin comandos._\n\n"
        "Para cancelar pulsa ❌ Cancelar."
    )


def activated_ok(name: str, expires_at: str) -> str:
    dl = days_left(expires_at)
    return (
        f"✅ *¡Acceso activado, {name}!*\n\n"
        f"📅 Válido hasta: `{fmt_date(expires_at)}`\n"
        f"⏳ *{dl} día{'s' if dl != 1 else ''}* de acceso\n\n"
        "🎉 ¡Ya puedes entrar al canal!"
    )


def renewed_ok(expires_at: str) -> str:
    dl = days_left(expires_at)
    return (
        f"🔄 *¡Renovación exitosa!*\n\n"
        f"📅 Nueva fecha: `{fmt_date(expires_at)}`\n"
        f"⏳ *{dl} día{'s' if dl != 1 else ''}* restantes"
    )


def err_code_invalid()    -> str: return "❌ *Código inválido o inexistente.*\nVerifica e inténtalo de nuevo."
def err_code_exhausted()  -> str: return "❌ *Este código ya no tiene usos disponibles.*\nContacta al administrador."
def err_already_active(expires_at: str) -> str:
    return (
        f"⚠️ *Ya tienes una suscripción activa.*\n\n"
        f"Vence el `{fmt_date(expires_at)}`\n\n"
        "Para extenderla usa el botón *🔄 Renovar*."
    )
def err_no_sub_to_renew() -> str: return "❌ *No tienes suscripción activa para renovar.*\nUsa primero *🔑 Activar código*."
def err_cancelled()       -> str: return "↩️ Operación cancelada."
def status_no_sub()       -> str: return "📭 *No tienes suscripción activa.*"


def expiry_warning(name: str, expires_at: str) -> str:
    dl = days_left(expires_at)
    return (
        f"⚠️ *¡Atención, {name}!*\n\n"
        f"Tu suscripción vence en *{dl} día{'s' if dl != 1 else ''}*\n"
        f"📅 `{fmt_date(expires_at)}`\n\n"
        "Pulsa *🔄 Renovar* en el menú para extender tu acceso."
    )


def expired_notice(name: str) -> str:
    return (
        f"🔴 *{name}, tu suscripción venció.*\n\n"
        "Has sido removido del canal.\n"
        "Activa un nuevo código cuando quieras volver 👇"
    )


# ── Admin ─────────────────────────────────────────────────────────────────────

def admin_menu() -> str:
    return "🛡️ *Panel de Administración*\n\nSelecciona una acción:"


def admin_code_created(code: str, days: int, max_uses: int) -> str:
    return (
        f"✅ *Código creado*\n\n"
        f"🔑 `{code}`\n"
        f"📅 {days} días · 👥 {max_uses} uso{'s' if max_uses != 1 else ''}"
    )


def admin_code_exists()   -> str: return "⚠️ Ya existe ese código. Elige otro nombre."
def admin_not_authorized() -> str: return "🚫 No tienes permisos de administrador."


def admin_ask_code_data() -> str:
    return (
        "✏️ *Nuevo código*\n\n"
        "Escribe en una línea:\n`CODIGO DIAS USOS`\n\n"
        "_Ejemplo:_ `VIP2024 30 5`\n\n"
        "Para cancelar escribe `cancelar`."
    )


def admin_ask_deactivate() -> str:
    return (
        "✏️ *Desactivar código*\n\n"
        "Escribe el nombre del código a desactivar.\n\n"
        "Para cancelar escribe `cancelar`."
    )


def admin_stats(s: dict) -> str:
    return (
        "📊 *Estadísticas*\n\n"
        f"👥 Usuarios totales:     *{s['total_users']}*\n"
        f"✅ Suscripciones activas: *{s['active_users']}*\n"
        f"⚠️  Vencen en ≤3 días:   *{s['expiring_soon']}*\n"
        f"📈 Activaciones hoy:     *{s['uses_today']}*\n\n"
        f"🔑 Códigos activos: *{s['active_codes']}* / {s['total_codes']} totales"
    )


def admin_codes_list(codes: list) -> str:
    if not codes:
        return "📭 No hay códigos activos."
    lines = ["🗂️ *Códigos activos*\n"]
    for c in codes[:20]:
        left = c["max_uses"] - c["used_times"]
        icon = "🟢" if left > 0 else "🔴"
        lines.append(f"{icon} `{c['code']}` — {c['days']}d — {c['used_times']}/{c['max_uses']} usos")
    if len(codes) > 20:
        lines.append(f"\n_...y {len(codes)-20} más_")
    return "\n".join(lines)


def admin_deactivated(code: str) -> str:
    return f"✅ Código `{code}` desactivado."
def admin_code_not_found()  -> str: return "❌ Código no encontrado."
def admin_user_kicked(uid, name) -> str:
    return f"🚫 *{name}* (`{uid}`) removido del canal."
def admin_kick_failed(uid)  -> str:
    return f"⚠️ No pude expulsar a `{uid}`. ¿El bot es admin del canal?"
def admin_new_activation(name, uid, code, expires_at) -> str:
    return (
        f"🆕 *Nueva activación*\n"
        f"👤 {name} (`{uid}`)\n"
        f"🔑 `{code}` · hasta `{fmt_date(expires_at)}`"
    )
def admin_renewal(name, uid, code, expires_at) -> str:
    return (
        f"🔄 *Renovación*\n"
        f"👤 {name} (`{uid}`)\n"
        f"🔑 `{code}` · nueva fecha `{fmt_date(expires_at)}`"
    )
