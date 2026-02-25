# 💎 VIP Bot — Canal Exclusivo Premium

> Bot de suscripción premium para canal privado de Telegram.
> Gestión completa de membresías, tickets de soporte, ruleta semanal, ranking y Mini App.
>
> **Desarrollado por DX**

---

## ✨ Funciones completas

### 👤 Experiencia de usuario

| Función | Descripción |
|---|---|
| 🔑 Activar código | Accede al canal privado con un código VIP |
| 🔄 Renovar acceso | Suma días a una suscripción activa |
| 💎 Mi membresía | Tarjeta visual con barra de progreso semántica (🟢🟡🔴) |
| 💎 Ver tarjeta VIP | Abre la Mini App con countdown en tiempo real |
| 🎁 Prueba gratis | 2 días de acceso gratuito (1 uso por usuario de por vida) |
| 🎰 Ruleta semanal | Gira una vez por semana y gana 1–7 días extra |
| 🎟️ Soporte | Abre tickets de soporte con respuesta del admin |
| 📋 Mis tickets | Historial de tickets y conversaciones |
| 📜 Mi historial | Actividad completa del usuario en el bot |
| 💬 Auto-respuesta | El bot responde mensajes de texto libre |
| 🚫 Blacklist | Usuarios baneados no pueden interactuar |

### 🛠️ Panel de administración

| Función | Comando/Botón |
|---|---|
| Panel completo | `/admin` |
| Generar código aleatorio | `DIAS USOS` → genera `VIP-XXXXXX` |
| Generar código personalizado | `CODIGO DIAS USOS [NOTA]` |
| Atajos rápidos de código | Botones 7d / 15d / 30d / 60d / 90d |
| Listar todos los códigos | Panel → Listar códigos |
| Estadísticas con gráficos ASCII | Panel → Estadísticas |
| Miembros activos con estado 🟢🟡🔴 | Panel → Miembros activos |
| Ranking top 10 miembros | Panel → Ranking |
| Tickets de soporte abiertos | Panel → Tickets soporte |
| Responder tickets | Panel → Tickets → Ver ticket → Responder |
| Cerrar / Reabrir tickets | Panel → Tickets → Acciones |
| Expulsar usuario | Panel → Miembros → Expulsar |
| Banear usuario | Panel → Blacklist → Banear |
| Desbanear usuario | Panel → Blacklist → Desbanear |
| `/ban USER_ID [razón]` | Comando directo |
| `/unban USER_ID` | Comando directo |
| `/adddays USER_ID DIAS` | Añadir días sin código |
| Broadcast masivo | Con preview + confirmación |
| Historial de broadcasts | Panel → Mantenimiento |
| Limpieza forzada de vencidos | Panel → Mantenimiento |
| Backup de DB | Panel → Mantenimiento → Backup |
| Log de auditoría | Panel → Mantenimiento → Auditoría |

### 🤖 Jobs automáticos

| Job | Frecuencia | Función |
|---|---|---|
| Limpieza vencidos | Cada hora | Expulsa del canal y notifica |
| Aviso vencimiento | Cada 12h | Notifica si vence en ≤3 días o ≤24h |
| Resumen diario | 08:00 UTC | Estadísticas del día al admin |

---

## 💎 Mini App de Telegram

La Mini App se abre pulsando **"💎 Ver tarjeta VIP"** dentro del bot (solo si tienes membresía activa).

- URL registrada: `https://t.me/subv1bot/membresia`
- Hosted en: `https://dxniel77.github.io/botFF/`
- Diseño luxury oscuro con tipografía premium
- Countdown en tiempo real (días, horas, minutos, segundos)
- Barra de progreso semántica con colores
- Banner de alerta automático si quedan ≤3 días
- Ticker tape rojo en estado crítico (≤24h)

---

## 🗂️ Estructura del proyecto

```
.
├── bot.py           ← Lógica principal, handlers, jobs
├── database.py      ← Capa de datos async (SQLite + WAL)
├── keyboards.py     ← Todos los InlineKeyboardMarkup
├── messages.py      ← Todos los textos con diseño premium
├── miniapp_index.html ← Mini App (subir a GitHub Pages)
├── requirements.txt
├── Dockerfile
└── railway.toml
```

---

## 🗃️ Base de datos

| Tabla | Descripción |
|---|---|
| `codes` | Códigos VIP con usos, días, nota y estado |
| `subscriptions` | Membresías activas con fechas y renovaciones |
| `blacklist` | Usuarios baneados permanentemente |
| `free_trials` | Registro de pruebas gratuitas usadas |
| `support_tickets` | Tickets de soporte con estado |
| `ticket_messages` | Mensajes de conversación por ticket |
| `ruleta_log` | Historial de ruletas jugadas |
| `stats` | Log de todos los eventos del bot |
| `audit_log` | Log de todas las acciones del admin |
| `broadcast_log` | Historial de broadcasts con resultados |

---

## ⚙️ Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `BOT_TOKEN` | Token de BotFather | `123456:ABC-...` |
| `ADMIN_ID` | ID numérico del admin | `123456789` |
| `CHANNEL_ID` | ID del canal privado | `-100123456789` |
| `DB_DIR` | Directorio de la DB (volumen Railway) | `/data` |

> `MINIAPP_URL` está hardcodeado en `bot.py` como `https://dxniel77.github.io/botFF/`

---

## 🚀 Deploy en Railway

### 1. Subir archivos a GitHub
```bash
git add .
git commit -m "VIP Bot - update"
git push
```

### 2. Variables en Railway
```
BOT_TOKEN=tu_token_aqui
ADMIN_ID=tu_id_aqui
CHANNEL_ID=id_del_canal_aqui
DB_DIR=/data
```

### 3. Volumen persistente
Railway → tu servicio → **Volumes** → **Add Volume** → Mount path: `/data`

### 4. Deploy automático
Railway detecta el `Dockerfile` y despliega automáticamente al hacer push.

---

## 📝 Guía de códigos

```bash
# Código aleatorio (genera VIP-XXXXXX)
30 5          →  30 días, 5 usos

# Código personalizado
BLACK30 30 1  →  código BLACK30, 30 días, 1 uso

# Con nota
PROMO7 7 10 LanzamientoJulio  →  código con nota
```

---

## 🎰 Ruleta semanal

- Disponible una vez cada 7 días por usuario
- Solo para usuarios con membresía activa
- Premios: 1 · 1 · 2 · 2 · 3 · 3 · 3 · 5 · 5 · 7 días (ponderado)
- Los días ganados se suman automáticamente a la membresía

---

## 🎟️ Sistema de soporte

- El usuario abre un ticket desde el menú principal
- El admin recibe notificación inmediata con botón de respuesta
- Conversación bidireccional con historial completo
- Estado: abierto / cerrado (ambos pueden cambiar el estado)
- Admin puede gestionar todos los tickets desde `/admin` → Tickets

---

## 🏆 Ranking (solo admin)

- Top 10 miembros por días acumulados totales
- Accesible desde `/admin` → Ranking
- Medallas 🥇🥈🥉🏅

---

## 🔒 Seguridad

- ✅ Blacklist permanente
- ✅ Verificación admin en cada operación
- ✅ Auditoría completa con timestamp
- ✅ Anti-colisión en códigos (30 intentos + fallback)
- ✅ Timeout de conversaciones: 5 minutos
- ✅ `drop_pending_updates=True`
- ✅ SQLite WAL mode

---

<div align="center">

**Desarrollado por DX · Canal VIP Exclusivo Premium**

</div>
