# 🤖 Bot de Suscripción v3 — 100% Botones

Bot profesional de acceso a canales privados de Telegram.
Interfaz completamente guiada por botones — sin comandos para los usuarios.

---

## ✨ Flujo del usuario (sin comandos)

```
/start
  └─► Menú principal  ──► [🔑 Activar código]  ──► escribe código ──► ✅ acceso + link
                       ──► [📊 Mi suscripción] ──► estado con barra de progreso
                       ──► [🔄 Renovar]         ──► escribe código ──► ✅ renovado
                       ──► [📞 Contactar admin] ──► link directo al admin
```

---

## 🛡️ Panel Admin (botones)

```
/admin
  └─► Panel  ──► [🔑 Generar código]    ──► escribe "CODIGO DIAS USOS" ──► ✅ creado
             ──► [🗂️ Listar códigos]   ──► tabla de todos los activos
             ──► [📊 Estadísticas]      ──► métricas en tiempo real
             ──► [👥 Usuarios activos]  ──► conteo + por vencer
             ──► [🔴 Desactivar código] ──► escribe código ──► confirma ──► ✅
             ──► [🔄 Actualizar]        ──► refresca el panel
```

---

## 🚀 Deploy en Railway (Plan Free)

### Variables de entorno

```
BOT_TOKEN   = token de BotFather
ADMIN_ID    = tu ID de Telegram (número)
CHANNEL_ID  = -1001234567890  (ID negativo del canal privado)
DB_DIR      = /data
```

> **¿Cómo obtener tu ADMIN_ID?** Escríbele a [@userinfobot](https://t.me/userinfobot)
> **¿Cómo obtener el CHANNEL_ID?** Reenvía un mensaje del canal al mismo bot

### Volumen persistente (CRÍTICO para no perder datos)

Railway → tu servicio → **Volumes** → **Add Volume** → Mount path: `/data`

### Subir a GitHub

```bash
git init && git add . && git commit -m "bot v3"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

Luego en Railway: **New Project → Deploy from GitHub repo**

---

## ⚙️ El bot debe ser admin del canal

En el canal → Administradores → agregar el bot con permisos:
- ✅ Invitar usuarios mediante enlace
- ✅ Expulsar miembros

---

## 🗂️ Estructura

```
telegram-bot/
├── bot.py          # Lógica, handlers, ConversationHandlers, jobs
├── database.py     # SQLite — codes, subscriptions, stats
├── messages.py     # Todos los textos (personaliza aquí)
├── keyboards.py    # Todos los botones inline
├── Dockerfile
├── railway.toml
├── requirements.txt
└── README.md
```

---

## ⏰ Automático (sin intervención)

| Evento | Acción |
|---|---|
| Código vence | Expulsa del canal + notifica al usuario + avisa al admin |
| Faltan 3 días | Aviso automático al usuario con botón de renovar |
| Usuario activa | Admin recibe notificación inmediata |
| Usuario renueva | Admin recibe notificación inmediata |
