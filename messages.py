"""
╔══════════════════════════════════════════════╗
║          DX VIP BOT — messages.py            ║
║   Todos los textos con diseño premium        ║
╚══════════════════════════════════════════════╝
"""

from datetime import datetime, timezone

# Separadores visuales
SEP   = "━━━━━━━━━━━━━━━━━━━━━━━━"
SEP_S = "─────────────────────────"
SEP_D = "══════════════════════════"


# ══════════════════════════════════════════════
# USUARIO — BIENVENIDA Y MENÚ
# ══════════════════════════════════════════════

def welcome(first_name: str) -> str:
    return (
        f"💎 *¡Bienvenido/a, {first_name}!*\n"
        f"`{SEP}`\n"
        f"Accede al contenido exclusivo más premium.\n"
        f"Aquí gestionas tu membresía VIP de forma\n"
        f"rápida, segura y sin complicaciones.\n"
        f"`{SEP_S}`\n"
        f"_Selecciona una opción del menú:_"
    )


HELP_TEXT = (
        f"ℹ️ *Guía de uso — DX VIP Bot*\n"
        f"`{SEP}`\n\n"
        f"🔑 *Activar código*\n"
        f"   Introduce tu código para acceder al canal.\n\n"
        f"🔄 *Renovar acceso*\n"
        f"   Suma días a tu membresía con un código nuevo.\n\n"
        f"💎 *Mi membresía*\n"
        f"   Consulta tu tarjeta VIP con días restantes.\n\n"
        f"🎁 *Prueba gratis*\n"
        f"   2 días de acceso sin coste (1 vez por usuario).\n\n"
        f"👥 *Mis referidos*\n"
        f"   Comparte tu link y gana días gratis.\n\n"
        f"📜 *Mi historial*\n"
        f"   Revisa toda tu actividad en el bot.\n\n"
        f"`{SEP_S}`\n"
        f"_¿Problemas? Contacta al administrador._"
)

AUTO_RESPONSE = (
    f"💬 *Hola, estoy aquí para ayudarte.*\n"
    f"`{SEP_S}`\n"
    f"Usa los botones del menú para gestionar\n"
    f"tu membresía VIP. Si tienes dudas, pulsa *Ayuda*.\n\n"
    f"_Escribe /start para ver el menú principal._"
)

BLACKLISTED_MESSAGE = (
    f"⛔ *Acceso denegado.*\n"
    f"`{SEP_S}`\n"
    f"_Tu cuenta ha sido bloqueada de este servicio._"
)


# ══════════════════════════════════════════════
# ACTIVACIÓN DE CÓDIGO
# ══════════════════════════════════════════════

ASK_CODE = (
    f"🔑 *Activar código de acceso*\n"
    f"`{SEP}`\n"
    f"Escribe tu código VIP a continuación:\n\n"
    f"_Ejemplo:_ `VIP-XK9F2M`"
)

CODE_NOT_FOUND = (
    f"❌ *Código no encontrado*\n"
    f"`{SEP_S}`\n"
    f"Revisa que esté escrito correctamente\n"
    f"y vuelve a intentarlo."
)

CODE_INACTIVE = (
    f"⛔ *Código agotado o inactivo*\n"
    f"`{SEP_S}`\n"
    f"Este código ya fue utilizado el máximo\n"
    f"de veces permitido o fue desactivado.\n\n"
    f"_Solicita un código nuevo al administrador._"
)

CODE_ALREADY_SUBSCRIBED = (
    f"ℹ️ *Ya tienes una membresía activa*\n"
    f"`{SEP_S}`\n"
    f"Para sumar días, usa *Renovar acceso*\n"
    f"con un código de renovación."
)


def code_activated(expires_at: datetime, invite_link: str, days: int) -> str:
    exp = expires_at.strftime("%d/%m/%Y a las %H:%M UTC")
    return (
        f"🎉 *¡Membresía activada con éxito!*\n"
        f"`{SEP}`\n\n"
        f"📅 *Vencimiento:* `{exp}`\n"
        f"⏱ *Duración:* `{days} días`\n\n"
        f"`{SEP_S}`\n"
        f"🔗 *Tu enlace de acceso exclusivo:*\n"
        f"{invite_link}\n\n"
        f"`{SEP_S}`\n"
        f"⚠️ _Enlace de un solo uso. No lo compartas._\n"
        f"_¡Disfruta tu acceso premium!_ 💎"
    )


# ══════════════════════════════════════════════
# RENOVACIÓN
# ══════════════════════════════════════════════

ASK_RENEW_CODE = (
    f"🔄 *Renovar membresía*\n"
    f"`{SEP}`\n"
    f"Escribe tu código de renovación:"
)

NO_SUBSCRIPTION_TO_RENEW = (
    f"❌ *Sin membresía registrada*\n"
    f"`{SEP_S}`\n"
    f"Primero activa un código con la opción\n"
    f"*Activar código*."
)


def code_renewed(new_expires: datetime, extra_days: int) -> str:
    exp = new_expires.strftime("%d/%m/%Y a las %H:%M UTC")
    return (
        f"✅ *¡Membresía renovada!*\n"
        f"`{SEP}`\n\n"
        f"➕ *Días añadidos:* `{extra_days}`\n"
        f"📅 *Nueva fecha límite:* `{exp}`\n\n"
        f"_Sigue disfrutando del contenido exclusivo._ 💎"
    )


# ══════════════════════════════════════════════
# TARJETA DE MEMBRESÍA
# ══════════════════════════════════════════════

NO_SUBSCRIPTION = (
    f"😕 *Sin membresía activa*\n"
    f"`{SEP_S}`\n"
    f"Todavía no tienes acceso al canal VIP.\n\n"
    f"Usa *Activar código* o *Prueba gratis*\n"
    f"para comenzar."
)


def membership_card(
    full_name: str,
    username: str | None,
    expires_at: datetime,
    created_at: datetime,
    code_used: str | None,
    renewals: int,
    total_days: int,
    referral_count: int,
) -> str:
    now = datetime.now(timezone.utc)

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    remaining_secs = (expires_at - now).total_seconds()
    total_secs     = (expires_at - created_at).total_seconds()
    days_left      = max(0, int(remaining_secs // 86400))
    hours_left     = max(0, int((remaining_secs % 86400) // 3600))

    # Barra de progreso con color semántico
    if remaining_secs <= 0:
        pct   = 0
        bar   = "░" * 12
        state = "❌ VENCIDA"
        color = "🔴"
    else:
        pct    = max(0, min(100, int((remaining_secs / max(total_secs, 1)) * 100)))
        filled = round(pct / 100 * 12)
        if pct > 50:
            fill_char = "█"
            color     = "🟢"
            state     = "✅ ACTIVA"
        elif pct > 20:
            fill_char = "▓"
            color     = "🟡"
            state     = "⚠️ PRONTO VENCE"
        else:
            fill_char = "▒"
            color     = "🔴"
            state     = "🚨 CRÍTICA"
        bar = fill_char * filled + "░" * (12 - filled)

    exp_str  = expires_at.strftime("%d/%m/%Y · %H:%M UTC")
    user_str = f"@{username}" if username else "sin usuario"

    return (
        f"💎 *TARJETA DE MEMBRESÍA VIP*\n"
        f"`{SEP_D}`\n\n"
        f"👤 *{full_name}*  _{user_str}_\n\n"
        f"{color} Estado:  *{state}*\n"
        f"📅 Vence:  `{exp_str}`\n"
        f"⏳ Resta:  *{days_left}d {hours_left}h*\n\n"
        f"`[{bar}]` {pct}%\n\n"
        f"`{SEP_S}`\n"
        f"🔑 Código:     `{code_used or 'N/A'}`\n"
        f"🔄 Renovaciones: `{renewals}`\n"
        f"📆 Días totales: `{total_days}`\n"
        f"👥 Referidos:   `{referral_count}`\n"
        f"`{SEP_D}`\n"
        f"_DX VIP Bot · Acceso Exclusivo_"
    )


# ══════════════════════════════════════════════
# REFERIDOS
# ══════════════════════════════════════════════

def referral_link_message(user_id: int, bot_username: str) -> str:
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    return (
        f"🔗 *Tu link de referido*\n"
        f"`{SEP}`\n\n"
        f"Comparte este enlace con tus amigos:\n"
        f"`{link}`\n\n"
        f"`{SEP_S}`\n"
        f"🎁 Cuando alguien se suscriba usando\n"
        f"tu link, *ganarás días gratis* de acceso.\n\n"
        f"💡 Cada referido válido = *+7 días* para ti."
    )


def my_referrals_message(count: int, bonus_total: int) -> str:
    return (
        f"👥 *Mis referidos*\n"
        f"`{SEP}`\n\n"
        f"🧑‍🤝‍🧑 Personas referidas: *{count}*\n"
        f"🎁 Días ganados por referidos: *{bonus_total}*\n\n"
        f"`{SEP_S}`\n"
        f"_Comparte tu link y sigue acumulando días._"
    )


REFERRAL_BONUS_GRANTED = (
    f"🎉 *¡Bonus de referido desbloqueado!*\n"
    f"`{SEP_S}`\n"
    f"Alguien que referiste acaba de activar\n"
    f"su membresía. ¡Se te han añadido *7 días*!\n\n"
    f"_Sigue compartiendo tu link para ganar más._ 🚀"
)


def referral_welcome(referrer_name: str) -> str:
    return (
        f"🎁 *¡Llegaste por invitación!*\n"
        f"`{SEP_S}`\n"
        f"Te invitó: *{referrer_name}*\n\n"
        f"Activa tu membresía y tu amigo/a\n"
        f"recibirá días extra de regalo. 🤝"
    )


# ══════════════════════════════════════════════
# PRUEBA GRATIS
# ══════════════════════════════════════════════

FREE_TRIAL_PROMPT = (
    f"🎁 *Prueba gratuita — 2 días*\n"
    f"`{SEP}`\n\n"
    f"Accede al contenido exclusivo durante\n"
    f"*2 días completamente gratis*.\n\n"
    f"⚠️ _Solo disponible una vez por usuario._\n\n"
    f"¿Deseas activarla ahora?"
)

FREE_TRIAL_ALREADY_USED = (
    f"⛔ *Prueba ya utilizada*\n"
    f"`{SEP_S}`\n"
    f"Ya usaste la prueba gratuita anteriormente.\n\n"
    f"_Adquiere un código de acceso completo._"
)


def free_trial_activated(expires_at: datetime, invite_link: str) -> str:
    exp = expires_at.strftime("%d/%m/%Y a las %H:%M UTC")
    return (
        f"🎉 *¡Prueba gratuita activada!*\n"
        f"`{SEP}`\n\n"
        f"📅 *Vence:* `{exp}`\n"
        f"⏱ *Duración:* `2 días`\n\n"
        f"🔗 *Tu enlace de acceso:*\n"
        f"{invite_link}\n\n"
        f"`{SEP_S}`\n"
        f"_Cuando venza, activa un código para continuar._ 💎"
    )


# ══════════════════════════════════════════════
# HISTORIAL DE USUARIO
# ══════════════════════════════════════════════

def user_history(events: list) -> str:
    if not events:
        return (
            f"📜 *Tu historial*\n"
            f"`{SEP_S}`\n"
            f"_No hay actividad registrada aún._"
        )
    lines = [f"📜 *Tu historial de actividad*\n`{SEP}`\n"]
    icons = {
        "code_activated": "🔑",
        "code_renewed":   "🔄",
        "free_trial":     "🎁",
        "referral_bonus": "👥",
        "start":          "👋",
    }
    for ev in events[:15]:
        ts   = ev["created_at"][:16].replace("T", " ")
        icon = icons.get(ev["event"], "•")
        lines.append(f"{icon} `{ts}` — _{ev['event']}_")
    lines.append(f"\n`{SEP_S}`\n_Mostrando últimos {min(15, len(events))} eventos._")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — PANEL
# ══════════════════════════════════════════════

def admin_panel_text(counts: dict) -> str:
    return (
        f"🛠️ *Panel de Administración — DX VIP Bot*\n"
        f"`{SEP_D}`\n\n"
        f"👥 Suscriptores totales:  *{counts['total']}*\n"
        f"✅ Activos ahora:         *{counts['active']}*\n"
        f"❌ Vencidos:              *{counts['expired']}*\n"
        f"📆 Días vendidos totales: *{counts['total_days']}*\n"
        f"🔄 Renovaciones totales:  *{counts['total_renewals']}*\n"
        f"`{SEP_D}`\n"
        f"_Selecciona una acción:_"
    )


# ══════════════════════════════════════════════
# ADMIN — GENERACIÓN DE CÓDIGO
# ══════════════════════════════════════════════

ADMIN_GEN_CODE_PROMPT = (
    f"➕ *Generar código VIP*\n"
    f"`{SEP}`\n\n"
    f"Escribe en uno de estos formatos:\n\n"
    f"• `DIAS USOS` → código aleatorio\n"
    f"  _Ej:_ `30 5`\n\n"
    f"• `CODIGO DIAS USOS` → personalizado\n"
    f"  _Ej:_ `VIP30 30 5`\n\n"
    f"• `CODIGO DIAS USOS NOTA` → con nota\n"
    f"  _Ej:_ `BLACK30 30 1 Cliente_Premium`\n\n"
    f"O usa los atajos de abajo:"
)

ADMIN_GEN_CODE_FORMAT_ERROR = (
    f"❌ *Formato incorrecto*\n"
    f"`{SEP_S}`\n"
    f"Usa: `DIAS USOS` o `CODIGO DIAS USOS`"
)

ADMIN_GEN_CODE_VALUE_ERROR = (
    "❌ Días y usos deben ser números enteros positivos."
)


def admin_code_created(code: str, days: int, max_uses: int,
                        auto: bool, note: str | None = None) -> str:
    tipo  = "🎲 Aleatorio" if auto else "✏️ Personalizado"
    nota  = f"\n📝 Nota: `{note}`" if note else ""
    return (
        f"✅ *Código creado*\n"
        f"`{SEP}`\n\n"
        f"🔑 Código:  `{code}`\n"
        f"📅 Días:    *{days}*\n"
        f"🔢 Usos:    *{max_uses}*\n"
        f"🏷️ Tipo:    {tipo}{nota}\n\n"
        f"`{SEP_S}`\n"
        f"_Copia y comparte con el usuario._"
    )


# ══════════════════════════════════════════════
# ADMIN — LISTADO CÓDIGOS
# ══════════════════════════════════════════════

def admin_codes_list(rows: list) -> str:
    if not rows:
        return f"📋 *Sin códigos registrados.*\n`{SEP_S}`"
    active   = [r for r in rows if r["is_active"]]
    inactive = [r for r in rows if not r["is_active"]]
    lines    = [f"📋 *Códigos registrados* ({len(rows)} total)\n`{SEP}`\n"]
    if active:
        lines.append(f"✅ *Activos ({len(active)}):*")
        for r in active:
            note = f" _{r['note']}_" if r["note"] else ""
            lines.append(
                f"  `{r['code']}` — {r['days']}d — {r['used_count']}/{r['max_uses']} usos{note}"
            )
    if inactive:
        lines.append(f"\n❌ *Inactivos ({len(inactive)}):*")
        for r in inactive[:10]:
            lines.append(f"  ~~`{r['code']}`~~ — {r['days']}d — {r['used_count']}/{r['max_uses']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — ESTADÍSTICAS CON ASCII
# ══════════════════════════════════════════════

def admin_stats_text(summary: dict, recent: list,
                      daily_events: list, daily_users: list) -> str:
    lines = [f"📊 *Estadísticas del bot*\n`{SEP_D}`\n"]

    # Eventos totales
    if summary:
        lines.append("📌 *Eventos totales:*")
        max_val = max(summary.values()) if summary else 1
        for event, cnt in list(summary.items())[:8]:
            bar_len = round(cnt / max_val * 10)
            bar     = "█" * bar_len + "░" * (10 - bar_len)
            lines.append(f"  `{bar}` {cnt:>4}  _{event}_")
    else:
        lines.append("_Sin eventos aún._")

    # Nuevos usuarios últimos 7 días
    if daily_users:
        lines.append(f"\n👥 *Nuevos usuarios (7 días):*")
        max_u = max(r["cnt"] for r in daily_users) if daily_users else 1
        for row in daily_users:
            bar_len = round(row["cnt"] / max_u * 10)
            bar     = "█" * bar_len + "░" * (10 - bar_len)
            day     = row["day"][5:]  # MM-DD
            lines.append(f"  `{bar}` {row['cnt']:>3}  {day}")

    # Últimos eventos
    if recent:
        lines.append(f"\n🕐 *Últimos eventos:*")
        for ev in recent[:8]:
            ts  = ev["created_at"][5:16].replace("T", " ")
            uid = str(ev["user_id"] or "-")[:10]
            lines.append(f"  `{ts}` {ev['event']} _{uid}_")

    lines.append(f"\n`{SEP_D}`")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — MIEMBROS
# ══════════════════════════════════════════════

def admin_members_text(rows: list) -> str:
    if not rows:
        return f"👥 *Sin suscriptores activos.*\n`{SEP_S}`"
    now    = datetime.now(timezone.utc)
    lines  = [f"👥 *Miembros activos* ({len(rows)})\n`{SEP}`\n"]
    for r in rows:
        name  = r["full_name"] or "Sin nombre"
        user  = f"@{r['username']}" if r["username"] else f"id:{r['user_id']}"
        exp   = datetime.fromisoformat(r["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        dleft = max(0, int((exp - now).total_seconds() // 86400))
        emoji = "🟢" if dleft > 7 else ("🟡" if dleft > 2 else "🔴")
        lines.append(f"{emoji} *{name}* ({user}) — {dleft}d restantes")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — BÚSQUEDA
# ══════════════════════════════════════════════

ADMIN_SEARCH_PROMPT = (
    f"🔍 *Buscar usuario*\n"
    f"`{SEP_S}`\n"
    f"Escribe ID numérico, @username o nombre:"
)
ADMIN_SEARCH_NO_RESULTS = "🔍 Sin resultados para esa búsqueda."


def admin_search_results(rows: list) -> str:
    lines = [f"🔍 *Resultados ({len(rows)})*\n`{SEP}`\n"]
    for r in rows:
        name  = r["full_name"] or "Sin nombre"
        user  = f"@{r['username']}" if r["username"] else "sin @"
        exp   = r["expires_at"][:16].replace("T", " ")
        lines.append(
            f"👤 *{name}* ({user})\n"
            f"   🆔 `{r['user_id']}`\n"
            f"   📅 Vence: `{exp}`\n"
            f"   🔑 Código: `{r['code_used'] or 'N/A'}`\n"
            f"   🔄 Renovaciones: `{r['renewals']}`\n"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — EXPULSAR / BAN / UNBAN
# ══════════════════════════════════════════════

ADMIN_KICK_PROMPT = (
    f"🚫 *Expulsar usuario*\n"
    f"`{SEP_S}`\n"
    f"Escribe el ID numérico del usuario:"
)
ADMIN_BAN_PROMPT = (
    f"🔇 *Banear usuario*\n"
    f"`{SEP_S}`\n"
    f"Escribe: `USER_ID RAZÓN`\n"
    f"_Ej:_ `123456789 Fraude`"
)
ADMIN_UNBAN_PROMPT = (
    f"✅ *Desbanear usuario*\n"
    f"`{SEP_S}`\n"
    f"Escribe el ID numérico a desbanear:"
)
ADMIN_KICK_NOT_FOUND = "❌ Usuario no encontrado en la base de datos."


def admin_kick_confirm_text(row) -> str:
    name = row["full_name"] or "Sin nombre"
    user = f"@{row['username']}" if row["username"] else f"id:{row['user_id']}"
    return (
        f"⚠️ *¿Confirmar expulsión?*\n"
        f"`{SEP_S}`\n"
        f"👤 {name} ({user})\n"
        f"🆔 `{row['user_id']}`\n\n"
        f"_Se eliminará del canal y de la DB._"
    )


def admin_kicked_ok(user_id: int) -> str:
    return f"✅ Usuario `{user_id}` expulsado correctamente."


def admin_banned_ok(user_id: int) -> str:
    return (
        f"🔇 Usuario `{user_id}` añadido a la blacklist.\n"
        f"_No podrá usar el bot ni activar códigos._"
    )


def admin_unbanned_ok(user_id: int) -> str:
    return f"✅ Usuario `{user_id}` eliminado de la blacklist."


ADMIN_UNBAN_NOT_FOUND = "❌ Ese usuario no está en la blacklist."
ADMIN_KICK_ERROR      = "❌ Error al expulsar. Puede que ya no esté en el canal."


# ══════════════════════════════════════════════
# ADMIN — BLACKLIST
# ══════════════════════════════════════════════

def admin_blacklist_text(rows: list) -> str:
    if not rows:
        return f"🔇 *Blacklist vacía.*\n`{SEP_S}`"
    lines = [f"🔇 *Blacklist* ({len(rows)} usuarios)\n`{SEP}`\n"]
    for r in rows:
        name   = r["full_name"] or "Sin nombre"
        user   = f"@{r['username']}" if r["username"] else "sin @"
        reason = r["reason"] or "Sin razón"
        date   = r["banned_at"][:10]
        lines.append(f"• `{r['user_id']}` — *{name}* ({user})\n  _{reason}_ · {date}")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — BROADCAST
# ══════════════════════════════════════════════

ADMIN_BROADCAST_PROMPT = (
    f"📢 *Broadcast masivo*\n"
    f"`{SEP}`\n\n"
    f"Escribe el mensaje a enviar a *todos*\n"
    f"los suscriptores activos.\n\n"
    f"_Soporta Markdown: *negrita*, _cursiva_, `código`_"
)


def admin_broadcast_preview(text: str, count: int) -> str:
    return (
        f"📢 *Vista previa del broadcast*\n"
        f"`{SEP}`\n\n"
        f"{text}\n\n"
        f"`{SEP_S}`\n"
        f"👥 Se enviará a *{count}* suscriptores activos.\n\n"
        f"¿Confirmas el envío?"
    )


def admin_broadcast_done(sent: int, failed: int) -> str:
    return (
        f"📢 *Broadcast completado*\n"
        f"`{SEP_S}`\n"
        f"✅ Enviados:  *{sent}*\n"
        f"❌ Fallidos: *{failed}*\n\n"
        f"_Los fallidos son usuarios que bloquearon el bot._"
    )


def admin_broadcast_history_text(rows: list) -> str:
    if not rows:
        return f"📢 *Sin broadcasts anteriores.*\n`{SEP_S}`"
    lines = [f"📢 *Historial de broadcasts*\n`{SEP}`\n"]
    for r in rows:
        ts   = r["created_at"][:16].replace("T", " ")
        prev = r["message"][:60].replace("\n", " ")
        lines.append(
            f"📅 `{ts}` — ✅{r['sent_count']} ❌{r['fail_count']}\n"
            f"   _{prev}..._"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — AUDITORÍA
# ══════════════════════════════════════════════

def admin_audit_text(rows: list) -> str:
    if not rows:
        return f"📋 *Sin entradas en auditoría.*\n`{SEP_S}`"
    lines = [f"📋 *Log de auditoría* (últimas {len(rows)})\n`{SEP}`\n"]
    for r in rows:
        ts     = r["created_at"][5:16].replace("T", " ")
        target = f" → `{r['target_id']}`" if r["target_id"] else ""
        detail = f" _{r['detail']}_"       if r["detail"]    else ""
        lines.append(f"`{ts}` *{r['action']}*{target}{detail}")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# ADMIN — ADDDAYS / RESUMEN DIARIO
# ══════════════════════════════════════════════

def admin_adddays_ok(user_id: int, days: int, new_exp: datetime) -> str:
    exp = new_exp.strftime("%d/%m/%Y %H:%M UTC")
    return (
        f"✅ *Días añadidos correctamente*\n"
        f"`{SEP_S}`\n"
        f"👤 Usuario: `{user_id}`\n"
        f"➕ Días añadidos: *{days}*\n"
        f"📅 Nueva fecha: `{exp}`"
    )


ADMIN_ADDDAYS_NOT_FOUND = "❌ Usuario no encontrado en la base de datos."
ADMIN_ADDDAYS_FORMAT_ERROR = (
    "❌ Formato: `/adddays USER_ID DIAS`\n_Ej:_ `/adddays 123456789 30`"
)


def daily_summary(counts: dict, new_today: int, expired_today: int) -> str:
    return (
        f"☀️ *Resumen diario — DX VIP Bot*\n"
        f"`{SEP_D}`\n\n"
        f"👥 Total suscriptores:  *{counts['total']}*\n"
        f"✅ Activos:             *{counts['active']}*\n"
        f"❌ Vencidos:            *{counts['expired']}*\n\n"
        f"`{SEP_S}`\n"
        f"📈 Nuevos hoy:          *{new_today}*\n"
        f"📉 Vencidos hoy:        *{expired_today}*\n"
        f"`{SEP_D}`\n"
        f"_Generado automáticamente._"
    )


# ══════════════════════════════════════════════
# NOTIFICACIONES AUTOMÁTICAS (JOBS)
# ══════════════════════════════════════════════

def warning_3d(days_left: int) -> str:
    return (
        f"⚠️ *Tu membresía vence pronto*\n"
        f"`{SEP}`\n\n"
        f"Te quedan aproximadamente *{days_left} días*\n"
        f"de acceso al canal exclusivo.\n\n"
        f"_Renueva ahora para no perder el acceso._ 💎"
    )


def warning_1d() -> str:
    return (
        f"🚨 *¡Último día de membresía!*\n"
        f"`{SEP}`\n\n"
        f"Tu acceso vence en menos de *24 horas*.\n\n"
        f"_Activa un código de renovación ahora\n"
        f"para no quedarte sin acceso._ ⚡"
    )


def subscription_expired_msg() -> str:
    return (
        f"😔 *Tu membresía ha vencido*\n"
        f"`{SEP}`\n\n"
        f"Has sido retirado/a del canal exclusivo.\n\n"
        f"Para volver a acceder, activa un nuevo\n"
        f"código desde el menú principal. 🔑"
    )


# ══════════════════════════════════════════════
# ERRORES Y GENÉRICOS
# ══════════════════════════════════════════════

GENERIC_ERROR        = f"❌ *Error inesperado.* Intenta de nuevo."
NOT_ADMIN            = f"⛔ No tienes permisos para esta acción."
OPERATION_CANCELLED  = f"❌ *Operación cancelada.*"
TIMEOUT_MSG          = f"⏱ *Tiempo agotado.* Operación cancelada."
