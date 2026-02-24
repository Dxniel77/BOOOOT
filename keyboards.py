"""
keyboards.py — Todos los teclados inline del bot
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Activar código",   callback_data="activate")],
        [InlineKeyboardButton("📊 Mi suscripción",   callback_data="my_sub")],
        [InlineKeyboardButton("🔄 Renovar",          callback_data="renew")],
        [InlineKeyboardButton("📞 Contactar admin",  callback_data="contact_admin")],
    ])


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Generar código",      callback_data="admin_gen_code"),
         InlineKeyboardButton("🗂️ Listar códigos",     callback_data="admin_list_codes")],
        [InlineKeyboardButton("📊 Estadísticas",        callback_data="admin_stats"),
         InlineKeyboardButton("👥 Miembros activos",    callback_data="admin_members")],
        [InlineKeyboardButton("🚨 Intrusos expulsados", callback_data="admin_intruders"),
         InlineKeyboardButton("🔍 Buscar usuario",      callback_data="admin_search")],
        [InlineKeyboardButton("🔴 Desactivar código",   callback_data="admin_deactivate"),
         InlineKeyboardButton("👢 Expulsar usuario",    callback_data="admin_kick")],
        [InlineKeyboardButton("🔄 Actualizar",          callback_data="admin_refresh")],
    ])


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menú principal", callback_data="main_menu")]
    ])


def back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Volver al panel", callback_data="admin_back")]
    ])


def confirm_deactivate_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data=f"admin_confirm_deactivate:{code}")],
        [InlineKeyboardButton("❌ Cancelar",  callback_data="admin_back")],
    ])


def confirm_kick_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar expulsión", callback_data=f"admin_confirm_kick:{user_id}")],
        [InlineKeyboardButton("❌ Cancelar",             callback_data="admin_back")],
    ])
