# 💎 DX VIP Bot

> Bot de suscripción premium para canal privado de Telegram.
> Gestión completa de membresías, referidos, blacklist, broadcast y auditoría.

---

## ✨ Características completas

### 👤 Experiencia de usuario
| Función | Descripción |
|---|---|
| 🔑 Activar código | Accede al canal privado con un código VIP |
| 🔄 Renovar acceso | Suma días a una suscripción activa |
| 💎 Tarjeta de membresía | Visualización premium con barra de progreso con color semántico (verde/amarillo/rojo) |
| 🎁 Prueba gratis | 2 días de acceso gratuito (1 uso por usuario de por vida) |
| 🔗 Sistema de referidos | Link personalizado; cada referido exitoso regala +7 días al referidor |
| 👥 Mis referidos | Historial de personas referidas y días ganados |
| 📜 Mi historial | Actividad completa del usuario en el bot |
| 💬 Auto-respuesta | El bot responde inteligentemente a mensajes de texto libre |
| 🚫 Blacklist | Usuarios baneados no pueden interactuar con el bot |

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
| Buscar usuario | Por ID, @username o nombre |
| Expulsar usuario | Con confirmación de seguridad |
| Banear usuario | Panel → Blacklist → Banear |
| Desbanear usuario | Panel → Blacklist → Desbanear |
| `/ban USER_ID [razón]` | Comando directo |
| `/unban USER_ID` | Comando directo |
| `/adddays USER_ID DIAS` | Añadir días sin código |
| Broadcast masivo | Con preview + confirmación |
| Historial de broadcasts | Panel → Mantenimiento |
| Intrusos detectados | Scan de canal privado |
| Limpieza forzada de vencidos | Panel → Mantenimiento |
| Backup de DB | Envía el archivo `.db` al admin |
| Log de auditoría | Cada acción admin queda registrada |

### 🤖 Automatizaciones (Jobs)
| Job | Frecuencia | Función |
|---|---|---|
| Limpieza vencidos | Cada hora | Expulsa del canal y notifica |
| Scan de intrusos | Cada 30 min | Detecta fantasmas / intrusos |
| Aviso 3 días | Cada 12h | Notifica si vence en ≤3 días |
| Aviso 1 día | Cada 12h | Notifica si vence en ≤24h |
| Resumen diario | 08:00 UTC | Estadísticas del día al admin |

---

## 🗂️ Estructura del proyecto

```
.
├── bot.py           ← Lógica principal, handlers, jobs
├── database.py      ← Capa de datos async (SQLite + WAL)
├── keyboards.py     ← Todos los InlineKeyboardMarkup
├── messages.py      ← Todos los textos con diseño premium
├── requirements.txt
├── Dockerfile
└── railway.toml
```

---

## 🗃️ Esquema de la base de datos

| Tabla | Descripción |
|---|---|
| `codes` | Códigos VIP con usos, días, nota y estado |
| `subscriptions` | Membresías activas con fechas, renovaciones y referido |
| `blacklist` | Usuarios baneados permanentemente |
| `referrals` | Registro de referidos y bonus entregados |
| `free_trials` | Registro de pruebas gratuitas usadas |
| `stats` | Log de todos los eventos del bot |
| `audit_log` | Log de todas las acciones del administrador |
| `broadcast_log` | Historial de broadcasts con resultados |

---

## ⚙️ Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `BOT_TOKEN` | Token de BotFather | `123456:ABC-...` |
| `ADMIN_ID` | ID numérico del admin | `123456789` |
| `CHANNEL_ID` | ID del canal privado | `-100123456789` |
| `DB_DIR` | Directorio de la DB (volumen Railway) | `/data` |

---

## 🚀 Deploy en Railway

### 1. Preparar el repositorio
```bash
git init
git add .
git commit -m "DX VIP Bot - Initial deploy"
```

### 2. Crear proyecto en Railway
1. Ve a [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Conecta tu repositorio

### 3. Añadir volumen persistente
1. En Railway: tu servicio → **Volumes** → **Add Volume**
2. Mount path: `/data`

### 4. Configurar variables de entorno
En Railway → Variables:
```
BOT_TOKEN=tu_token_aqui
ADMIN_ID=tu_id_aqui
CHANNEL_ID=id_del_canal_aqui
DB_DIR=/data
```

### 5. Deploy automático
Railway detecta el `Dockerfile` y despliega automáticamente.

---

## 📝 Guía de códigos

### Formato al generar desde el panel admin

```
# Código aleatorio (genera VIP-XXXXXX)
30 5          →  30 días, 5 usos

# Código personalizado
BLACK30 30 1  →  código BLACK30, 30 días, 1 uso

# Con nota descriptiva
PROMO7 7 10 LanzamientoJulio  →  código con nota
```

### Ejemplos de códigos generados
```
VIP-XK9F2M   (aleatorio)
VIP-A3PQ7R   (aleatorio)
BLACK30       (personalizado)
PROMO7        (personalizado)
```

---

## 🎨 Mejoras visuales implementadas

- **Separadores premium** `━━━━━━━━━━━━━━━━━━━━━━━━` en todos los mensajes
- **Tarjeta de membresía** estilo visual con barra de progreso y estado semántico
- **Colores de estado**: 🟢 Activa / 🟡 Pronto vence / 🔴 Crítica
- **Gráficos ASCII** en estadísticas admin con barras proporcionales
- **Emojis ricos** consistentes en toda la interfaz
- **Bienvenida personalizada** con el nombre del usuario

---

## 💡 Mejoras visuales adicionales que puedes hacer

### En BotFather (sin código)
- Sube una **foto de perfil** al bot: logo 640×640px con fondo oscuro y letras doradas
- Configura la **descripción corta**: `"Canal VIP Exclusivo · Activa tu acceso aquí 💎"`
- Configura los **comandos visibles**:
  ```
  start - Menú principal
  admin - Panel de administración
  adddays - Añadir días a usuario
  ban - Banear usuario
  unban - Desbanear usuario
  ```

### Banner de bienvenida (mejora opcional)
Puedes reemplazar el mensaje de bienvenida por una **foto + caption**:
```python
# En start_handler, cambiar reply_text por:
await update.message.reply_photo(
    photo="URL_O_FILE_ID_DEL_BANNER",
    caption=msg.welcome(user.first_name),
    reply_markup=kb.main_menu(),
    parse_mode=ParseMode.MARKDOWN,
)
```
Diseña el banner en Canva: **1280×640px**, fondo oscuro, tipografía dorada, logo del canal.

### Mini App de Telegram (próximo nivel)
Para una experiencia de app móvil completa con gráficos reales,
historial visual y panel admin interactivo, se puede desarrollar
una **Telegram Web App** (HTML/CSS/JS) que se abre dentro del bot.

---

## 🔒 Seguridad

- ✅ Blacklist permanente: los baneados no pueden interactuar
- ✅ Verificación en cada callback: el admin_id se valida en cada operación
- ✅ Auditoría completa: toda acción del admin queda registrada con timestamp
- ✅ Anti-colisión en códigos: bucle de 30 intentos + fallback con `secrets.token_hex`
- ✅ Timeout de conversaciones: 5 minutos de inactividad cancela automáticamente
- ✅ `drop_pending_updates=True`: evita conflictos al reiniciar
- ✅ SQLite WAL mode: escrituras concurrentes seguras

---

## 📜 Licencia

Proyecto privado. Todos los derechos reservados.

---

<div align="center">

**Desarrollado con 💎 por DX**

*DX VIP Bot · Canal Exclusivo Premium*

</div>
