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
        f"Accede al canal VIP exclusivo activando\n"
        f"tu código o renovando tu membresía.\n\n"
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

def ticket_list_header() -> str:
    return f"📋 *Mis tickets*\n{SEP}\n\n"

def ticket_item(ticket_id: int, subject: str, status: str, date: str) -> str:
    st_icon  = "📬" if status == "open" else "✅"
    st_label = "Abierto" if status == "open" else "Cerrado"
    return f"{st_icon} *#{ticket_id:04d}* — _{subject}_\n   {st_label} · `{date}`\n\n"

def ticket_detail(ticket_id: int, subject: str, status: str, messages: list) -> str:
    st_icon = "📬" if status == "open" else "✅"
    txt = (
        f"🎟️ *Ticket #{ticket_id:04d}* {st_icon}\n"
        f"{SEP}\n\n"
        f"📌 _{subject}_\n\n"
        f"{SEP_S}\n\n"
    )
    for msg in messages:
        who = "🛡️ *Soporte*" if msg["is_admin"] else "👤 *Tú*"
        txt += f"{who} · `{msg['sent_at'][:16]}`\n{msg['message']}\n\n"
    return txt

def ticket_reply_sent() -> str:
    return "✅ *Mensaje enviado* al ticket."

def ticket_closed_user() -> str:
    return (
        f"✅ *Ticket cerrado*\n"
        f"{SEP}\n\n"
        f"Si necesitas más ayuda, abre un nuevo ticket."
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

def admin_panel_text(stats: dict) -> str:
    return (
        f"🛡️ *Panel de Administración*\n"
        f"{SEP}\n\n"
        f"👥 Miembros activos: *{stats['active']}*\n"
        f"📊 Total histórico: *{stats['total']}*\n"
        f"🔴 Vencen en ≤3 días: *{stats['expiring_3d']}*\n"
        f"🔑 Códigos activos: *{stats['codes']}*\n"
        f"🎁 Pruebas usadas: *{stats['trials']}*\n"
        f"🚫 Baneados: *{stats['banned']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"👑 Admins: *{stats['admins']}*\n"
        f"📆 Nuevos hoy: *{stats['new_today']}*\n\n"
        f"{SEP_S}\n"
        f"Selecciona una acción:"
    )

def admin_code_created(code: str, days: int, uses: int, note: str, expires_at: str = None) -> str:
    txt = (
        f"✅ *Código generado*\n"
        f"{SEP}\n\n"
        f"🔑 Código: `{code}`\n"
        f"📅 Días: *{days}*\n"
        f"🔁 Usos: *{uses}*\n"
        f"📝 Nota: _{note or 'Sin nota'}_"
    )
    if expires_at:
        txt += f"\n⏰ Expira: `{expires_at}`"
    return txt

def admin_codes_list(codes: list) -> str:
    if not codes:
        return f"📋 *Sin códigos*\n{SEP}\n\nNo hay códigos registrados."
    txt = f"📋 *Códigos VIP* ({len(codes)})\n{SEP}\n\n"
    for c in codes[:20]:
        active = "🟢" if c["is_active"] else "🔴"
        exp    = f" · exp:{c['expires_at'][:10]}" if c["expires_at"] else ""
        txt += f"{active} `{c['code']}` — {c['days']}d · {c['used_count']}/{c['max_uses']}{exp}\n"
    return txt

def admin_members_list(members: list) -> str:
    if not members:
        return f"👥 *Sin miembros activos*\n{SEP}"
    txt = f"👥 *Miembros activos ({len(members)})*\n{SEP}\n\n"
    for m in members:
        expiry    = datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        days_left = max(0, (expiry - datetime.now(timezone.utc)).days)
        dot  = "🟢" if days_left > 3 else ("🟡" if days_left > 1 else "🔴")
        name = m["first_name"] or "Sin nombre"
        un   = f"@{m['username']}" if m["username"] else f"ID:{m['user_id']}"
        txt += f"{dot} *{name}* {un} — {days_left}d\n"
    return txt

def admin_stats(stats: dict, members: list) -> str:
    active  = stats["active"]
    total   = stats["total"]
    pct     = int((active / max(1, total)) * 100)
    filled  = int((pct / 100) * 20)
    bar     = "█" * filled + "░" * (20 - filled)
    soon    = sum(1 for m in members if 0 < (datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days <= 3)
    critical= sum(1 for m in members if 0 < (datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days <= 1)
    return (
        f"📊 *Estadísticas VIP*\n"
        f"{SEP}\n\n"
        f"👥 Activos / Total: *{active} / {total}*\n"
        f"`{bar}` {pct}%\n\n"
        f"🔴 Críticos (≤1d):  *{critical}*\n"
        f"🟡 Pronto vencen:   *{soon}*\n"
        f"🟢 Saludables:      *{active - soon}*\n\n"
        f"🎁 Pruebas gratis:  *{stats['trials']}*\n"
        f"🚫 Baneados:        *{stats['banned']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"📆 Nuevos hoy:      *{stats['new_today']}*"
    )

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

def admin_blacklist_list(bl: list) -> str:
    if not bl:
        return f"✅ *Blacklist vacía*\n{SEP}\n\nNo hay usuarios baneados."
    txt = f"🚫 *Blacklist ({len(bl)})*\n{SEP}\n\n"
    for b in bl:
        txt += f"• `{b['user_id']}` — _{b['reason'] or 'Sin razón'}_\n"
    return txt

def admin_broadcast_preview(message: str, filter_label: str) -> str:
    return (
        f"📢 *Preview del broadcast*\n"
        f"{SEP}\n\n"
        f"🎯 Segmento: *{filter_label}*\n\n"
        f"{message}\n\n"
        f"{SEP_S}\n"
        f"¿Enviar a este segmento?"
    )

def admin_broadcast_done(sent: int, failed: int, filter_label: str) -> str:
    return (
        f"✅ *Broadcast completado*\n"
        f"{SEP}\n\n"
        f"🎯 Segmento: *{filter_label}*\n"
        f"✉️ Enviados: *{sent}*\n"
        f"❌ Fallidos: *{failed}*"
    )

def admin_tickets_list(tickets: list, open_only: bool = False) -> str:
    if not tickets:
        label = "abiertos" if open_only else "registrados"
        return f"🎟️ *Sin tickets {label}*\n{SEP}"
    title = "Tickets abiertos" if open_only else "Todos los tickets"
    txt   = f"🎟️ *{title} ({len(tickets)})*\n{SEP}\n\n"
    for t in tickets:
        st   = "📬" if t["status"] == "open" else "✅"
        name = t["first_name"] or "Sin nombre"
        txt += f"{st} *#{t['id']:04d}* · {name}\n   📌 _{t['subject']}_\n   `{t['updated_at'][:16]}`\n\n"
    return txt

def admin_ticket_detail(ticket, messages: list) -> str:
    st_icon = "📬" if ticket["status"] == "open" else "✅"
    txt = (
        f"🎟️ *Ticket #{ticket['id']:04d}* {st_icon}\n"
        f"{SEP}\n\n"
        f"👤 {ticket['first_name']} · `{ticket['user_id']}`\n"
        f"📌 _{ticket['subject']}_\n"
        f"📅 `{ticket['created_at'][:16]}`\n\n"
        f"{SEP_S}\n\n"
    )
    for msg in messages:
        who = "🛡️ *Admin*" if msg["is_admin"] else "👤 *Usuario*"
        txt += f"{who} · `{msg['sent_at'][:16]}`\n{msg['message']}\n\n"
    return txt

def admin_ticket_reply_sent(ticket_id: int) -> str:
    return f"✅ Respuesta enviada al ticket *#{ticket_id:04d}*."

def admin_ranking(members: list) -> str:
    if not members:
        return f"🏆 *Ranking VIP*\n{SEP}\n\nSin datos todavía."
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 20
    txt    = f"🏆 *Ranking VIP · Top {len(members)}*\n{SEP}\n\n"
    for i, m in enumerate(members):
        name = m["first_name"] or "Sin nombre"
        un   = f"@{m['username']}" if m["username"] else f"ID:{m['user_id']}"
        txt += f"{medals[i]} *{name}* {un}\n   📊 {m['total_days']} días acumulados\n\n"
    return txt

def admin_admins_list(admins: list, main_admin_id: int) -> str:
    txt = f"👑 *Administradores*\n{SEP}\n\n"
    txt += f"⭐ *Admin principal* · `{main_admin_id}`\n\n"
    if not admins:
        txt += "_Sin admins secundarios._"
    else:
        for a in admins:
            name = a["first_name"] or "Sin nombre"
            un   = f"@{a['username']}" if a["username"] else f"ID:{a['user_id']}"
            txt += f"👑 *{name}* {un}\n   Añadido: `{a['added_at'][:10]}`\n\n"
    return txt

def admin_add_admin_success(user_id: int) -> str:
    return f"✅ Admin `{user_id}` añadido correctamente."

def admin_remove_admin_success(user_id: int) -> str:
    return f"✅ Admin `{user_id}` removido correctamente."

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
