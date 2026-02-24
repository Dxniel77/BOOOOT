# 🤖 Bot de Suscripción por Códigos — Telegram

## Variables de entorno en Railway

| Variable     | Descripción                                          |
|--------------|------------------------------------------------------|
| `BOT_TOKEN`  | Token de tu bot (de @BotFather)                      |
| `ADMIN_ID`   | Tu user ID de Telegram (número entero)               |
| `CHANNEL_ID` | ID del canal privado (ej: `-1001234567890`)          |

> Para obtener el CHANNEL_ID: añade @userinfobot a tu canal y escribe cualquier mensaje.

---

## Comandos ADMIN

| Comando | Descripción |
|---------|-------------|
| `/generar` | Código random, 30 días, 1 uso |
| `/generar 60` | Código random, 60 días, 1 uso |
| `/generar 30 5` | Código random, 30 días, 5 usos |
| `/generar JUAN-VIP` | Código personalizado, 30 días, 1 uso |
| `/generar JUAN-VIP 30` | Código personalizado, 30 días, 1 uso |
| `/generar JUAN-VIP 30 5` | Código personalizado, 30 días, 5 usos |
| `/listar` | Ver todos los códigos creados |
| `/revocar CODIGO` | Desactiva el código y expulsa a sus usuarios |
| `/usuarios` | Ver todos los suscriptores activos |
| `/expulsar USER_ID` | Expulsar manualmente a un usuario |

## Comandos USUARIO

| Comando | Descripción |
|---------|-------------|
| `/start` | Mensaje de bienvenida |
| `/activar CODIGO` | Activar suscripción con un código |
| `/mi_suscripcion` | Ver estado y fecha de vencimiento |

---

## Configuración del canal privado

1. Crea un canal privado en Telegram.
2. **Añade tu bot como administrador** del canal con permisos para:
   - Invitar usuarios
   - Expulsar usuarios
3. Asegúrate de que el canal esté en modo **privado** (sin link público).

---

## Deploy en Railway

```bash
# 1. Sube estos archivos a un repositorio GitHub
# 2. Conecta el repo en railway.app
# 3. Agrega las 3 variables de entorno
# 4. Deploy → usa "worker" como proceso (ya configurado en Procfile)
```

**IMPORTANTE:** Si Railway falla con errores de versión, ve a:
`Settings → Deploy → Clear Build Cache` y redespliega.

---

## Cómo funciona internamente

- Los datos se guardan en `data.json` (en Railway persiste mientras el servicio corra).
- Cada hora el bot revisa automáticamente si alguna suscripción venció y expulsa al usuario.
- Los links de invitación son de **un solo uso** y expiran junto con la suscripción.
