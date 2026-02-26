"""
keyboards.py — VIP Bot · Teclados inline
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

MINIAPP_URL = "https://dxniel77.github.io/botFF/"


# ══════════════════════════════════════════════════════════════
# USUARIO — Menú principal
# ══════════════════════════════════════════════════════════════
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Activar código",  callback_data="activate"),
            InlineKeyboardButton("🔄 Renovar acceso",  callback_data="renew"),
        ],
        [
            InlineKeyboardButton("💎 Mi membresía VIP", web_app=WebAppInfo(url=MINIAPP_URL)),
        ],
        [
            InlineKeyboardButton("🎁 Prueba gratis 30d", callback_data="free_trial"),
        ],
        [
            InlineKeyboardButton("🎟️ Soporte",         callback_data="support"),
            InlineKeyboardButton("📜 Mi historial",    callback_data="history"),
        ],
    ])


# ══════════════════════════════════════════════════════════════
# USUARIO — Soporte / Tickets
# ══════════════════════════════════════════════════════════════
def support_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Abrir nuevo ticket",  callback_data="ticket_new")],
        [InlineKeyboardButton("📋 Mis tickets",         callback_data="ticket_list")],
        [InlineKeyboardButton("🏠 Menú principal",      callback_data="main_menu")],
    ])

def ticket_user_actions(ticket_id: int, is_open: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_open:
        rows.append([InlineKeyboardButton("💬 Responder",     callback_data=f"ticket_reply_{ticket_id}")])
        rows.append([InlineKeyboardButton("✅ Cerrar ticket",  callback_data=f"ticket_close_{ticket_id}")])
    else:
        rows.append([InlineKeyboardButton("🔄 Reabrir ticket", callback_data=f"ticket_reopen_{ticket_id}")])
    rows.append([InlineKeyboardButton("« Volver", callback_data="ticket_list")])
    return InlineKeyboardMarkup(rows)

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancelar", callback_data="main_menu")
    ]])


# ══════════════════════════════════════════════════════════════
# ADMIN — Panel principal
# ══════════════════════════════════════════════════════════════
def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Generar código",   callback_data="adm_gen_code"),
            InlineKeyboardButton("📋 Listar códigos",   callback_data="adm_list_codes"),
        ],
        [
            InlineKeyboardButton("👥 Miembros activos", callback_data="adm_members"),
            InlineKeyboardButton("📊 Estadísticas",     callback_data="adm_stats"),
        ],
        [
            InlineKeyboardButton("🎟️ Tickets",          callback_data="adm_tickets"),
            InlineKeyboardButton("🏆 Ranking",          callback_data="adm_ranking"),
        ],
        [
            InlineKeyboardButton("🚫 Blacklist",        callback_data="adm_blacklist"),
            InlineKeyboardButton("📢 Broadcast",        callback_data="adm_broadcast"),
        ],
        [
            InlineKeyboardButton("👑 Admins",           callback_data="adm_admins"),
            InlineKeyboardButton("🔧 Mantenimiento",    callback_data="adm_maintenance"),
        ],
    ])

def admin_gen_code_shortcuts() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("7d · 1 uso",       callback_data="adm_quick_7"),
            InlineKeyboardButton("15d · 1 uso",      callback_data="adm_quick_15"),
            InlineKeyboardButton("30d · 1 uso",      callback_data="adm_quick_30"),
        ],
        [
            InlineKeyboardButton("60d · 1 uso",      callback_data="adm_quick_60"),
            InlineKeyboardButton("90d · 1 uso",      callback_data="adm_quick_90"),
            InlineKeyboardButton("✏️ Personalizado", callback_data="adm_custom_code"),
        ],
        [InlineKeyboardButton("« Panel",             callback_data="adm_panel")],
    ])

def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« Panel admin", callback_data="adm_panel")
    ]])


# ══════════════════════════════════════════════════════════════
# ADMIN — Tickets
# ══════════════════════════════════════════════════════════════
def admin_tickets_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📬 Tickets abiertos",  callback_data="adm_tickets_open")],
        [InlineKeyboardButton("📁 Todos los tickets", callback_data="adm_tickets_all")],
        [InlineKeyboardButton("« Panel",              callback_data="adm_panel")],
    ])

def admin_ticket_actions(ticket_id: int, is_open: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("💬 Responder", callback_data=f"adm_ticket_reply_{ticket_id}")]]
    if is_open:
        rows.append([InlineKeyboardButton("✅ Cerrar",   callback_data=f"adm_ticket_close_{ticket_id}")])
    else:
        rows.append([InlineKeyboardButton("🔄 Reabrir", callback_data=f"adm_ticket_reopen_{ticket_id}")])
    rows.append([InlineKeyboardButton("« Tickets", callback_data="adm_tickets")])
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════════
# ADMIN — Broadcast segmentado
# ══════════════════════════════════════════════════════════════
def admin_broadcast_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Todos los miembros",      callback_data="adm_bc_all")],
        [InlineKeyboardButton("🔴 Vencen en 1-3 días",     callback_data="adm_bc_critical")],
        [InlineKeyboardButton("🟡 Vencen en 4-7 días",     callback_data="adm_bc_warning")],
        [InlineKeyboardButton("🟢 Más de 7 días activos",  callback_data="adm_bc_healthy")],
        [InlineKeyboardButton("« Panel",                   callback_data="adm_panel")],
    ])

def confirm_action(yes_data: str, no_data: str = "adm_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=yes_data),
        InlineKeyboardButton("❌ Cancelar",  callback_data=no_data),
    ]])


# ══════════════════════════════════════════════════════════════
# ADMIN — Blacklist
# ══════════════════════════════════════════════════════════════
def admin_blacklist_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚫 Banear",    callback_data="adm_ban_input"),
            InlineKeyboardButton("✅ Desbanear", callback_data="adm_unban_input"),
        ],
        [InlineKeyboardButton("📋 Ver blacklist", callback_data="adm_blacklist_list")],
        [InlineKeyboardButton("« Panel",          callback_data="adm_panel")],
    ])


# ══════════════════════════════════════════════════════════════
# ADMIN — Admins
# ══════════════════════════════════════════════════════════════
def admin_admins_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Añadir admin",    callback_data="adm_add_admin")],
        [InlineKeyboardButton("➖ Quitar admin",    callback_data="adm_remove_admin")],
        [InlineKeyboardButton("📋 Ver admins",      callback_data="adm_list_admins")],
        [InlineKeyboardButton("« Panel",            callback_data="adm_panel")],
    ])


# ══════════════════════════════════════════════════════════════
# ADMIN — Mantenimiento
# ══════════════════════════════════════════════════════════════
def admin_maintenance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Limpiar vencidos",     callback_data="adm_clean_expired")],
        [InlineKeyboardButton("📤 Exportar CSV",         callback_data="adm_export_csv")],
        [InlineKeyboardButton("👻 Scan intrusos",        callback_data="adm_scan_intruders")],
        [InlineKeyboardButton("📜 Historial broadcasts", callback_data="adm_broadcast_history")],
        [InlineKeyboardButton("📋 Log auditoría",        callback_data="adm_audit_log")],
        [InlineKeyboardButton("💾 Backup DB",            callback_data="adm_backup")],
        [InlineKeyboardButton("« Panel",                 callback_data="adm_panel")],
    ])
