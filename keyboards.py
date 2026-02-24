"""
╔══════════════════════════════════════════════╗
║          DX VIP BOT — keyboards.py           ║
║   Todos los teclados InlineKeyboard          ║
╚══════════════════════════════════════════════╝
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ══════════════════════════════════════════════
# MENÚ PRINCIPAL (USUARIO)
# ══════════════════════════════════════════════

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Activar código",      callback_data="activate_code"),
            InlineKeyboardButton("🔄 Renovar acceso",      callback_data="renew_code"),
        ],
        [
            InlineKeyboardButton("💎 Mi membresía",        callback_data="my_subscription"),
            InlineKeyboardButton("👥 Mis referidos",       callback_data="my_referrals"),
        ],
        [
            InlineKeyboardButton("🎁 Prueba gratis 2d",    callback_data="free_trial"),
            InlineKeyboardButton("📜 Mi historial",        callback_data="my_history"),
        ],
        [
            InlineKeyboardButton("🔗 Obtener link referido", callback_data="get_referral_link"),
        ],
        [
            InlineKeyboardButton("ℹ️ Ayuda",               callback_data="help"),
        ],
    ])


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menú principal", callback_data="main_menu")]
    ])


def cancel_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ])


def confirm_free_trial() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sí, activar 2 días gratis", callback_data="confirm_free_trial"),
            InlineKeyboardButton("❌ No", callback_data="main_menu"),
        ]
    ])


# ══════════════════════════════════════════════
# PANEL ADMIN
# ══════════════════════════════════════════════

def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Generar código",      callback_data="admin_gen_code"),
            InlineKeyboardButton("📋 Listar códigos",      callback_data="admin_list_codes"),
        ],
        [
            InlineKeyboardButton("📊 Estadísticas",        callback_data="admin_stats"),
            InlineKeyboardButton("👥 Miembros activos",    callback_data="admin_members"),
        ],
        [
            InlineKeyboardButton("🔍 Buscar usuario",      callback_data="admin_search"),
            InlineKeyboardButton("🚫 Expulsar usuario",    callback_data="admin_kick"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast",           callback_data="admin_broadcast"),
            InlineKeyboardButton("🕵️ Intrusos",            callback_data="admin_intruders"),
        ],
        [
            InlineKeyboardButton("🔇 Blacklist",           callback_data="admin_blacklist"),
            InlineKeyboardButton("📋 Auditoría",           callback_data="admin_audit"),
        ],
        [
            InlineKeyboardButton("⚙️ Mantenimiento",       callback_data="admin_maintenance"),
            InlineKeyboardButton("🔄 Actualizar",          callback_data="admin_refresh"),
        ],
    ])


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Panel admin", callback_data="admin_back")]
    ])


def admin_gen_code_shortcuts() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("7d / 1 uso",    callback_data="admin_quickcode_7_1"),
            InlineKeyboardButton("15d / 1 uso",   callback_data="admin_quickcode_15_1"),
            InlineKeyboardButton("30d / 1 uso",   callback_data="admin_quickcode_30_1"),
        ],
        [
            InlineKeyboardButton("30d / 5 usos",  callback_data="admin_quickcode_30_5"),
            InlineKeyboardButton("60d / 1 uso",   callback_data="admin_quickcode_60_1"),
            InlineKeyboardButton("90d / 1 uso",   callback_data="admin_quickcode_90_1"),
        ],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


def admin_confirm_kick(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data=f"admin_kick_confirm_{user_id}"),
            InlineKeyboardButton("❌ Cancelar",  callback_data="admin_back"),
        ]
    ])


def admin_confirm_ban(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔇 Sí, banear",  callback_data=f"admin_ban_confirm_{user_id}"),
            InlineKeyboardButton("❌ Cancelar",     callback_data="admin_back"),
        ]
    ])


def admin_broadcast_confirm(msg_preview: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Enviar a todos", callback_data="admin_broadcast_confirm"),
            InlineKeyboardButton("❌ Cancelar",        callback_data="admin_back"),
        ]
    ])


def admin_maintenance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Limpiar vencidos ahora",     callback_data="admin_force_cleanup")],
        [InlineKeyboardButton("🔎 Escanear intrusos ahora",    callback_data="admin_force_scan")],
        [InlineKeyboardButton("💾 Backup DB al admin",         callback_data="admin_backup_db")],
        [InlineKeyboardButton("📜 Historial broadcasts",       callback_data="admin_broadcast_history")],
        [InlineKeyboardButton("⬅️ Panel admin",                callback_data="admin_back")],
    ])


def admin_blacklist_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Banear usuario",   callback_data="admin_ban"),
            InlineKeyboardButton("➖ Desbanear usuario", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("📋 Ver blacklist",       callback_data="admin_view_blacklist")],
        [InlineKeyboardButton("⬅️ Panel admin",         callback_data="admin_back")],
    ])
