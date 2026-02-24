import os
import json
import random
import string
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, ContextTypes

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]
ADMIN_ID    = int(os.environ["ADMIN_ID"])
CHANNEL_ID  = int(os.environ["CHANNEL_ID"])   # ID del canal privado (ej: -1001234567890)
DB_FILE     = "data.json"

# ─── BASE DE DATOS (JSON simple) ──────────────────────────────────────────────
def load_db():
    if not os.path.exists(DB_FILE):
        return {"codes": {}, "users": {}}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2, default=str)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def random_code(length=8):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

def is_admin(user_id):
    return user_id == ADMIN_ID

# ─── COMANDOS ADMIN ───────────────────────────────────────────────────────────

async def generar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Uso: /generar [CODIGO] [dias] [usos]
    Ejemplos:
      /generar                    → código random, 30 días, 1 uso
      /generar 60                 → código random, 60 días, 1 uso
      /generar JUAN-VIP 30 5      → código personalizado, 30 días, 5 usos
      /generar 30 5               → código random, 30 días, 5 usos
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return

    args = ctx.args
    codigo = None
    dias = 30
    usos = 1

    if len(args) == 0:
        codigo = random_code()

    elif len(args) == 1:
        # puede ser días (número) o código (texto)
        if args[0].isdigit():
            dias = int(args[0])
            codigo = random_code()
        else:
            codigo = args[0].upper()

    elif len(args) == 2:
        # CODIGO dias  ó  dias usos
        if args[0].isdigit():
            dias = int(args[0])
            usos = int(args[1])
            codigo = random_code()
        else:
            codigo = args[0].upper()
            dias = int(args[1])

    elif len(args) >= 3:
        codigo = args[0].upper()
        dias = int(args[1])
        usos = int(args[2])

    db = load_db()
    if codigo in db["codes"]:
        await update.message.reply_text(f"⚠️ El código <b>{codigo}</b> ya existe.", parse_mode="HTML")
        return

    expira = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    db["codes"][codigo] = {
        "dias": dias,
        "usos_max": usos,
        "usos_usados": 0,
        "expira_codigo": expira,   # fecha límite para canjear
        "activo": True,
        "usuarios": []
    }
    save_db(db)

    await update.message.reply_text(
        f"✅ <b>Código creado</b>\n\n"
        f"🔑 Código: <code>{codigo}</code>\n"
        f"📅 Válido por: <b>{dias} días</b> tras activarlo\n"
        f"👥 Usos máximos: <b>{usos}</b>\n"
        f"⏳ Caduca si no se usa antes de: <b>{expira}</b>",
        parse_mode="HTML"
    )


async def listar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra todos los códigos activos."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return

    db = load_db()
    codes = db["codes"]

    if not codes:
        await update.message.reply_text("📭 No hay códigos creados.")
        return

    lines = ["<b>📋 Códigos registrados:</b>\n"]
    for cod, info in codes.items():
        estado = "✅" if info["activo"] else "❌"
        lines.append(
            f"{estado} <code>{cod}</code> — {info['usos_usados']}/{info['usos_max']} usos — "
            f"{info['dias']}d — caduca: {info['expira_codigo']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def revocar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /revocar CODIGO — desactiva el código y expulsa a sus usuarios."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return

    if not ctx.args:
        await update.message.reply_text("Uso: /revocar CODIGO")
        return

    codigo = ctx.args[0].upper()
    db = load_db()

    if codigo not in db["codes"]:
        await update.message.reply_text(f"❌ Código <b>{codigo}</b> no encontrado.", parse_mode="HTML")
        return

    db["codes"][codigo]["activo"] = False
    expulsados = 0

    for user_id in db["codes"][codigo]["usuarios"]:
        try:
            await ctx.bot.ban_chat_member(CHANNEL_ID, user_id)
            await ctx.bot.unban_chat_member(CHANNEL_ID, user_id)  # ban + unban = expulsar sin bloquear
            expulsados += 1
        except Exception as e:
            print(f"Error expulsando {user_id}: {e}")

    save_db(db)
    await update.message.reply_text(
        f"🚫 Código <b>{codigo}</b> revocado. {expulsados} usuario(s) expulsado(s).",
        parse_mode="HTML"
    )


async def usuarios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /usuarios — lista todos los suscriptores activos."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return

    db = load_db()
    lines = ["<b>👥 Suscriptores activos:</b>\n"]
    total = 0

    for user_id, info in db["users"].items():
        if info["activo"]:
            lines.append(
                f"• ID: <code>{user_id}</code> | @{info.get('username','—')} | "
                f"código: <code>{info['codigo']}</code> | vence: {info['vence']}"
            )
            total += 1

    if total == 0:
        await update.message.reply_text("📭 No hay suscriptores activos.")
        return

    lines.append(f"\n<b>Total: {total}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def expulsar_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /expulsar USER_ID — expulsa manualmente a un usuario."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return

    if not ctx.args:
        await update.message.reply_text("Uso: /expulsar USER_ID")
        return

    user_id = int(ctx.args[0])
    db = load_db()

    try:
        await ctx.bot.ban_chat_member(CHANNEL_ID, user_id)
        await ctx.bot.unban_chat_member(CHANNEL_ID, user_id)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return

    uid = str(user_id)
    if uid in db["users"]:
        db["users"][uid]["activo"] = False
        save_db(db)

    await update.message.reply_text(f"✅ Usuario <code>{user_id}</code> expulsado.", parse_mode="HTML")


# ─── COMANDOS USUARIO ─────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Para acceder al canal privado usa:\n\n"
        "<code>/activar TU_CODIGO</code>",
        parse_mode="HTML"
    )


async def activar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uso: /activar CODIGO"""
    if not ctx.args:
        await update.message.reply_text("Uso: /activar TU_CODIGO")
        return

    codigo = ctx.args[0].upper()
    user = update.effective_user
    user_id = str(user.id)
    db = load_db()

    # Validaciones del código
    if codigo not in db["codes"]:
        await update.message.reply_text("❌ Código inválido.")
        return

    info = db["codes"][codigo]

    if not info["activo"]:
        await update.message.reply_text("❌ Este código ha sido desactivado.")
        return

    if info["usos_usados"] >= info["usos_max"]:
        await update.message.reply_text("❌ Este código ya alcanzó su límite de usos.")
        return

    # Verificar que el código no haya caducado para canjear
    if datetime.now() > datetime.strptime(info["expira_codigo"], "%Y-%m-%d %H:%M:%S"):
        await update.message.reply_text("❌ Este código ha expirado.")
        return

    # Verificar si el usuario ya tiene suscripción activa
    if user_id in db["users"] and db["users"][user_id]["activo"]:
        vence = db["users"][user_id]["vence"]
        await update.message.reply_text(f"ℹ️ Ya tienes acceso activo hasta <b>{vence}</b>.", parse_mode="HTML")
        return

    # Generar link de invitación de un solo uso
    try:
        vence_dt = datetime.now() + timedelta(days=info["dias"])
        invite = await ctx.bot.create_chat_invite_link(
            CHANNEL_ID,
            expire_date=vence_dt,
            member_limit=1,
            name=f"{codigo}-{user.id}"
        )
        link = invite.invite_link
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error al generar invitación: {e}")
        return

    # Registrar en DB
    vence_str = vence_dt.strftime("%Y-%m-%d %H:%M:%S")
    info["usos_usados"] += 1
    info["usuarios"].append(user.id)

    db["users"][user_id] = {
        "username": user.username or "",
        "nombre": user.full_name,
        "codigo": codigo,
        "vence": vence_str,
        "activo": True
    }
    save_db(db)

    await update.message.reply_text(
        f"🎉 <b>¡Código activado!</b>\n\n"
        f"📅 Tu acceso vence el: <b>{vence_str}</b>\n\n"
        f"🔗 Únete aquí (link de un solo uso):\n{link}",
        parse_mode="HTML"
    )


async def mi_suscripcion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra al usuario su estado de suscripción."""
    user_id = str(update.effective_user.id)
    db = load_db()

    if user_id not in db["users"] or not db["users"][user_id]["activo"]:
        await update.message.reply_text("❌ No tienes suscripción activa.")
        return

    info = db["users"][user_id]
    vence = datetime.strptime(info["vence"], "%Y-%m-%d %H:%M:%S")
    dias_restantes = (vence - datetime.now()).days

    await update.message.reply_text(
        f"✅ <b>Suscripción activa</b>\n\n"
        f"📅 Vence: <b>{info['vence']}</b>\n"
        f"⏳ Días restantes: <b>{dias_restantes}</b>\n"
        f"🔑 Código usado: <code>{info['codigo']}</code>",
        parse_mode="HTML"
    )


# ─── JOB: VERIFICAR VENCIMIENTOS ──────────────────────────────────────────────

async def check_expiries(ctx: ContextTypes.DEFAULT_TYPE):
    """Corre cada hora. Expulsa usuarios cuya suscripción venció."""
    db = load_db()
    now = datetime.now()
    expulsados = 0

    for user_id, info in db["users"].items():
        if not info["activo"]:
            continue
        vence = datetime.strptime(info["vence"], "%Y-%m-%d %H:%M:%S")
        if now >= vence:
            try:
                await ctx.bot.ban_chat_member(CHANNEL_ID, int(user_id))
                await ctx.bot.unban_chat_member(CHANNEL_ID, int(user_id))
                expulsados += 1
            except Exception as e:
                print(f"Error expulsando {user_id}: {e}")
            info["activo"] = False

    if expulsados:
        save_db(db)
        print(f"[check_expiries] {expulsados} usuario(s) expulsado(s) por vencimiento.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Admin
    app.add_handler(CommandHandler("generar",  generar))
    app.add_handler(CommandHandler("listar",   listar))
    app.add_handler(CommandHandler("revocar",  revocar))
    app.add_handler(CommandHandler("usuarios", usuarios))
    app.add_handler(CommandHandler("expulsar", expulsar_cmd))

    # Usuario
    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("activar",         activar))
    app.add_handler(CommandHandler("mi_suscripcion",  mi_suscripcion))

    # Job cada hora para revisar vencimientos
    app.job_queue.run_repeating(check_expiries, interval=3600, first=10)

    print("🤖 Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
