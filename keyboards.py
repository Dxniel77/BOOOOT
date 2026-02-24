"""
keyboards.py — Todos los teclados inline del bot.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ══════════════════════════════════════════════
#  MENÚ PRINCIPAL DE USUARIO
# ══════════════════════════════════════════════

def user_main_menu(has_sub: bool = False) -> InlineKeyboardMarkup:
    """Menú principal: 3 botones siempre visibles, Renovar solo si hay suscripción."""
    rows = [
        [InlineKeyboardButton("🔑 Activar código",   callback_data="u:activate_start")],
        [InlineKeyboardButton("📊 Ver mi suscripción", callback_data="u:status")],
    ]
    if has_sub:
        rows.append([InlineKeyboardButton("🔄 Renovar suscripción", callback_data="u:renew_start")])
    return InlineKeyboardMarkup(rows)


def user_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data="u:cancel")]
    ])


def user_after_success(has_sub: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 Ver mi suscripción", callback_data="u:status")],
        [InlineKeyboardButton("🏠 Menú principal",     callback_data="u:menu")],
    ]
    if has_sub:
        rows.insert(1, [InlineKeyboardButton("🔄 Renovar suscripción", callback_data="u:renew_start")])
    return InlineKeyboardMarkup(rows)


def user_status_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Renovar suscripción", callback_data="u:renew_start")],
        [InlineKeyboardButton("🏠 Menú principal",      callback_data="u:menu")],
    ])


# ══════════════════════════════════════════════
#  PANEL ADMIN
# ══════════════════════════════════════════════

def admin_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Generar código",    callback_data="a:gen_start"),
            InlineKeyboardButton("🗂️ Listar códigos",    callback_data="a:list"),
        ],
        [
            InlineKeyboardButton("📊 Estadísticas",      callback_data="a:stats"),
            InlineKeyboardButton("👥 Usuarios activos",  callback_data="a:users"),
        ],
        [
            InlineKeyboardButton("🔴 Desactivar código", callback_data="a:deact_start"),
        ],
        [
            InlineKeyboardButton("🔄 Actualizar",        callback_data="a:refresh"),
        ],
    ])


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Volver al panel", callback_data="a:menu")]
    ])


def admin_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancelar", callback_data="a:menu")]
    ])


def admin_confirm_deactivate(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sí, desactivar",  callback_data=f"a:deact_ok:{code}"),
            InlineKeyboardButton("❌ Cancelar",         callback_data="a:menu"),
        ]
    ])
