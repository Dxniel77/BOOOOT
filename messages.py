"""
messages.py — DX VIP Bot · Textos con diseño premium
"""

from datetime import datetime, timezone
from typing import Optional


SEP = "━━━━━━━━━━━━━━━━━━━━━━━━"
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
        f"Tu cuenta ha sido suspendida permanentemente.\n"
        f"Contacta a soporte si crees que es un error."
    )

# ── Membresía ──
def membership_card(first_name: str, expiry_str: str, days_left: int,
                    total_days: int, renewals: int, joined_at: str) -> str:
    pct = max(0, min(100, int((days_left / max(1, total_days)) * 100)))
    filled = int(pct / 5)
    bar_color = "🟢" if days_left > 3 else ("🟡" if days_left > 1 else "🔴")
    bar = bar_color * filled + "⬜" * (20 - filled)

    if days_left > 3:
        status = "🟢 Activa"
    elif days_left > 1:
        status = "🟡 Pronto vence"
    else:
        status = "🔴 Crítica"

    return (
        f"💎 *Tarjeta de Membresía VIP*\n"
        f"{SEP}\n\n"
        f"👤 *{first_name}*\n"
        f"Estado: {status}\n\n"
        f"`{bar}` {pct}%\n\n"
        f"📅 Vence: `{expiry_str}`\n"
        f"⏳ Días restantes: *{days_left}*\n"
        f"📊 Plan: {total_days} días totales\n"
        f"🔄 Renovaciones: {renewals}\n"
        f"📆 Miembro desde: `{joined_at}`\n\n"
        f"{SEP_S}\n"
        f"_Toca el botón para tu tarjeta visual interactiva_ 👇"
    )

def no_membership() -> str:
    return (
        f"💎 *Sin membresía activa*\n"
        f"{SEP}\n\n"
        f"No tienes un acceso VIP activo.\n\n"
        f"🔑 Activa un código VIP\n"
        f"🎁 O prueba 2 días gratis"
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
        f"Disfruta *2 días* de acceso VIP.\n"
        f"📅 Vence: `{expiry}`\n\n"
        f"_Recuerda que la prueba es por única vez._"
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
        f"El código no existe, ya fue usado\n"
        f"o fue desactivado. Verifica e intenta de nuevo."
    )

def expiry_warning(days_left: int) -> str:
    if days_left <= 1:
        icon, msg = "🔴", f"¡Tu acceso VIP vence en menos de *24 horas*!"
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
        "ticket": "🎟️",  "ruleta": "🎰"
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
        f"✏️ *Nuevo ticket de soporte*\n"
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
    st_icon = "📬" if status == "open" else "✅"
    st_label = "Abierto" if status == "open" else "Cerrado"
    return (
        f"{st_icon} *#{ticket_id:04d}* — _{subject}_\n"
        f"   {st_label} · `{date}`\n\n"
    )

def ticket_detail(ticket_id: int, subject: str, status: str, messages: list) -> str:
    st_icon = "📬" if status == "open" else "✅"
    st_label = "Abierto" if status == "open" else "Cerrado"
    txt = (
        f"🎟️ *Ticket #{ticket_id:04d}*\n"
        f"{SEP}\n\n"
        f"📌 _{subject}_\n"
        f"Estado: {st_icon} {st_label}\n\n"
        f"{SEP_S}\n\n"
    )
    for msg in messages:
        who = "🛡️ *Admin*" if msg["is_admin"] else "👤 *Tú*"
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
# RULETA
# ══════════════════════════════════════════════════════════════

def ruleta_menu(can_play: bool, next_play: str = "") -> str:
    if can_play:
        return (
            f"🎰 *Ruleta Semanal VIP*\n"
            f"{SEP}\n\n"
            f"¡Gira la ruleta y gana días extra!\n\n"
            f"🎁 Premios posibles: 1 · 2 · 3 · 5 · 7 días\n"
            f"🗓️ Disponible: *una vez por semana*\n\n"
            f"¿Listo para girar?"
        )
    else:
        return (
            f"🎰 *Ruleta Semanal VIP*\n"
            f"{SEP}\n\n"
            f"⏳ Ya participaste esta semana.\n\n"
            f"📅 Próxima tirada: *{next_play}*\n\n"
            f"_¡Vuelve pronto para ganar más días!_"
        )

def ruleta_spinning() -> str:
    return (
        f"🎰 *Girando la ruleta...*\n"
        f"{SEP}\n\n"
        f"╔══════════════╗\n"
        f"║  🎲 · 💎 · 🎯  ║\n"
        f"║  🔮 · ⭐ · 🎁  ║\n"
        f"║  🌟 · 🎰 · 🏆  ║\n"
        f"╚══════════════╝\n\n"
        f"_Determinando tu premio..._"
    )

RULETA_PRIZES = {1: "🥉", 2: "🥈", 3: "🥇", 5: "💎", 7: "👑"}

def ruleta_result(days_won: int, new_expiry: str) -> str:
    icon = RULETA_PRIZES.get(days_won, "🎁")
    return (
        f"🎉 *¡GANASTE {days_won} DÍAS!*\n"
        f"{SEP}\n\n"
        f"{icon} Premio: *+{days_won} días VIP*\n\n"
        f"📅 Nuevo vencimiento: `{new_expiry}`\n\n"
        f"_Regresa en 7 días para volver a girar._"
    )

def ruleta_no_membership() -> str:
    return (
        f"🎰 *Ruleta Semanal VIP*\n"
        f"{SEP}\n\n"
        f"⚠️ Necesitas una membresía activa\n"
        f"para participar en la ruleta."
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
        f"🔑 Códigos activos: *{stats['codes']}*\n"
        f"🎁 Pruebas usadas: *{stats['trials']}*\n"
        f"🚫 Baneados: *{stats['banned']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"📆 Nuevos hoy: *{stats['new_today']}*\n\n"
        f"{SEP_S}\n"
        f"Selecciona una acción:"
    )

def admin_code_created(code: str, days: int, uses: int, note: str) -> str:
    return (
        f"✅ *Código generado*\n"
        f"{SEP}\n\n"
        f"🔑 Código: `{code}`\n"
        f"📅 Días: *{days}*\n"
        f"🔁 Usos: *{uses}*\n"
        f"📝 Nota: _{note or 'Sin nota'}_"
    )

def admin_codes_list(codes: list) -> str:
    if not codes:
        return f"📋 *Sin códigos*\n{SEP}\n\nNo hay códigos registrados."
    txt = f"📋 *Códigos VIP*\n{SEP}\n\n"
    for c in codes[:20]:
        active = "🟢" if c["is_active"] else "🔴"
        txt += (
            f"{active} `{c['code']}` — {c['days']}d · "
            f"{c['used_count']}/{c['max_uses']} usos\n"
        )
    return txt

def admin_members_list(members: list) -> str:
    if not members:
        return f"👥 *Sin miembros activos*\n{SEP}"
    txt = f"👥 *Miembros activos ({len(members)})*\n{SEP}\n\n"
    for m in members:
        from datetime import timedelta
        expiry = datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        days_left = max(0, (expiry - datetime.now(timezone.utc)).days)
        if days_left > 3:
            dot = "🟢"
        elif days_left > 1:
            dot = "🟡"
        else:
            dot = "🔴"
        name = m["first_name"] or "Sin nombre"
        un = f"@{m['username']}" if m["username"] else f"ID:{m['user_id']}"
        txt += f"{dot} *{name}* {un} — {days_left}d\n"
    return txt

def admin_stats(stats: dict, members: list) -> str:
    active = stats["active"]
    total  = stats["total"]
    pct    = int((active / max(1, total)) * 100)

    bar_len = 20
    filled  = int((pct / 100) * bar_len)
    bar     = "█" * filled + "░" * (bar_len - filled)

    # Distribución por días restantes
    soon     = sum(1 for m in members if 0 < (datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days <= 3)
    critical = sum(1 for m in members if 0 < (datetime.strptime(m["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days <= 1)

    return (
        f"📊 *Estadísticas DX VIP*\n"
        f"{SEP}\n\n"
        f"👥 Activos / Total: *{active} / {total}*\n"
        f"`{bar}` {pct}%\n\n"
        f"🔴 Críticos (≤1d):   *{critical}*\n"
        f"🟡 Pronto vencen:    *{soon}*\n"
        f"🟢 Saludables:       *{active - soon}*\n\n"
        f"🎁 Pruebas gratis:   *{stats['trials']}*\n"
        f"🚫 Baneados:         *{stats['banned']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"📆 Nuevos hoy:       *{stats['new_today']}*"
    )

def admin_adddays_success(user_id: int, days: int, new_expiry: str) -> str:
    return (
        f"✅ *Días añadidos*\n"
        f"{SEP}\n\n"
        f"Usuario: `{user_id}`\n"
        f"Días añadidos: *+{days}*\n"
        f"Nuevo vencimiento: `{new_expiry}`"
    )

def admin_kick_confirm(user_id: int, name: str) -> str:
    return (
        f"⚠️ *Confirmar expulsión*\n"
        f"{SEP}\n\n"
        f"Vas a expulsar a *{name}* (`{user_id}`)\n"
        f"del canal VIP. ¿Confirmar?"
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

def admin_broadcast_preview(message: str) -> str:
    return (
        f"📢 *Preview del broadcast*\n"
        f"{SEP}\n\n"
        f"{message}\n\n"
        f"{SEP_S}\n"
        f"¿Enviar a todos los miembros activos?"
    )

def admin_broadcast_done(sent: int, failed: int) -> str:
    return (
        f"✅ *Broadcast completado*\n"
        f"{SEP}\n\n"
        f"✉️ Enviados: *{sent}*\n"
        f"❌ Fallidos: *{failed}*"
    )


# ── Admin Tickets ──
def admin_tickets_list(tickets: list, open_only: bool = False) -> str:
    if not tickets:
        label = "abiertos" if open_only else "registrados"
        return f"🎟️ *Sin tickets {label}*\n{SEP}"
    title = "Tickets abiertos" if open_only else "Todos los tickets"
    txt = f"🎟️ *{title} ({len(tickets)})*\n{SEP}\n\n"
    for t in tickets:
        st = "📬" if t["status"] == "open" else "✅"
        name = t["first_name"] or "Sin nombre"
        txt += (
            f"{st} *#{t['id']:04d}* · {name}\n"
            f"   📌 _{t['subject']}_\n"
            f"   `{t['updated_at'][:16]}`\n\n"
        )
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
        who = "🛡️ *Admin*" if msg["is_admin"] else f"👤 *Usuario*"
        txt += f"{who} · `{msg['sent_at'][:16]}`\n{msg['message']}\n\n"
    return txt

def admin_ticket_reply_sent(ticket_id: int) -> str:
    return f"✅ Respuesta enviada al ticket *#{ticket_id:04d}*."


# ── Admin Ranking ──
def admin_ranking(members: list) -> str:
    if not members:
        return f"🏆 *Ranking VIP*\n{SEP}\n\nSin datos todavía."
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 20
    txt = f"🏆 *Ranking VIP · Top {len(members)}*\n{SEP}\n\n"
    for i, m in enumerate(members):
        name = m["first_name"] or "Sin nombre"
        un = f"@{m['username']}" if m["username"] else f"ID:{m['user_id']}"
        txt += f"{medals[i]} *{name}* {un}\n   📊 {m['total_days']} días acumulados\n\n"
    return txt


# ── Daily summary ──
def daily_summary(stats: dict) -> str:
    return (
        f"☀️ *Resumen diario · DX VIP*\n"
        f"{SEP}\n\n"
        f"👥 Miembros activos: *{stats['active']}*\n"
        f"📆 Nuevos hoy: *{stats['new_today']}*\n"
        f"🎟️ Tickets abiertos: *{stats['tickets_open']}*\n"
        f"🚫 Baneados: *{stats['banned']}*\n\n"
        f"_DX VIP Bot · {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_"
    )
