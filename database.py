"""
database.py — Bot de Suscripción v3
OPTIMIZACIONES:
  ✅ aiosqlite — no bloquea el Event Loop
  ✅ WAL mode — concurrencia sin bloqueos
  ✅ Índices en columnas de búsqueda frecuente
  ✅ invite_link por usuario para revocar al vencer
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_DIR  = os.getenv("DB_DIR", ".")
DB_PATH = os.path.join(DB_DIR, "bot.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code        TEXT PRIMARY KEY,
                days        INTEGER NOT NULL,
                max_uses    INTEGER NOT NULL DEFAULT 1,
                used_count  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id      INTEGER PRIMARY KEY,
                username     TEXT,
                full_name    TEXT,
                expires_at   TEXT NOT NULL,
                code_used    TEXT,
                invite_link  TEXT,
                warned_3d    INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event       TEXT NOT NULL,
                user_id     INTEGER,
                detail      TEXT,
                created_at  TEXT NOT NULL
            )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_sub_expires  ON subscriptions(expires_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sub_warned   ON subscriptions(warned_3d)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_codes_active ON codes(is_active)")

        await db.commit()
    logger.info("Base de datos inicializada en %s", DB_PATH)


# ══════════════════════════════════════════════
#  CÓDIGOS
# ══════════════════════════════════════════════

async def create_code(code: str, days: int, max_uses: int = 1) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                "INSERT INTO codes (code, days, max_uses, created_at) VALUES (?, ?, ?, ?)",
                (code.upper(), days, max_uses, datetime.now().isoformat())
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    except Exception as e:
        logger.error("create_code error: %s", e)
        return False


async def get_code(code: str) -> Optional[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM codes WHERE code = ? AND is_active = 1", (code.upper(),)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("get_code error: %s", e)
        return None


async def use_code(code: str, user_id: int, username: str, full_name: str, invite_link: str = None) -> Optional[int]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row

            async with db.execute(
                "SELECT * FROM codes WHERE code = ? AND is_active = 1", (code.upper(),)
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return None

            code_data = dict(row)
            if code_data["used_count"] >= code_data["max_uses"]:
                return None

            days = code_data["days"]
            now  = datetime.now()

            async with db.execute(
                "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
            ) as cur:
                existing = await cur.fetchone()

            base = (
                max(datetime.fromisoformat(existing["expires_at"]), now)
                if existing else now
            )
            new_expiry = base + timedelta(days=days)

            await db.execute("""
                INSERT INTO subscriptions
                    (user_id, username, full_name, expires_at, code_used, invite_link, warned_3d, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username    = excluded.username,
                    full_name   = excluded.full_name,
                    expires_at  = excluded.expires_at,
                    code_used   = excluded.code_used,
                    invite_link = excluded.invite_link,
                    warned_3d   = 0,
                    updated_at  = excluded.updated_at
            """, (user_id, username, full_name, new_expiry.isoformat(),
                  code.upper(), invite_link, now.isoformat(), now.isoformat()))

            new_count = code_data["used_count"] + 1
            await db.execute(
                "UPDATE codes SET used_count = ?, is_active = ? WHERE code = ?",
                (new_count, 0 if new_count >= code_data["max_uses"] else 1, code.upper())
            )
            await db.execute(
                "INSERT INTO stats (event, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
                ("code_used", user_id, code.upper(), now.isoformat())
            )
            await db.commit()
        return days
    except Exception as e:
        logger.error("use_code error: %s", e)
        return None


async def deactivate_code(code: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                "UPDATE codes SET is_active = 0 WHERE code = ?", (code.upper(),)
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error("deactivate_code error: %s", e)
        return False


async def list_active_codes() -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM codes WHERE is_active = 1 ORDER BY created_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("list_active_codes error: %s", e)
        return []


# ══════════════════════════════════════════════
#  SUSCRIPCIONES
# ══════════════════════════════════════════════

async def get_subscription(user_id: int) -> Optional[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("get_subscription error: %s", e)
        return None


async def get_all_active_subscriptions() -> list:
    try:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE expires_at > ? ORDER BY expires_at ASC", (now,)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_all_active_subscriptions error: %s", e)
        return []


async def get_all_active_user_ids() -> set:
    try:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            async with db.execute(
                "SELECT user_id FROM subscriptions WHERE expires_at > ?", (now,)
            ) as cur:
                rows = await cur.fetchall()
        return {row[0] for row in rows}
    except Exception as e:
        logger.error("get_all_active_user_ids error: %s", e)
        return set()


async def search_user(query: str) -> list:
    """Busca por username, nombre o user_id."""
    try:
        like = f"%{query}%"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM subscriptions
                WHERE username LIKE ? OR full_name LIKE ? OR CAST(user_id AS TEXT) LIKE ?
                ORDER BY expires_at DESC LIMIT 10
            """, (like, like, like)) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("search_user error: %s", e)
        return []


async def get_expired_subscriptions() -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE expires_at < ?",
                (datetime.now().isoformat(),)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_expired_subscriptions error: %s", e)
        return []


async def get_expiring_soon(days: int = 3) -> list:
    try:
        now   = datetime.now()
        limit = now + timedelta(days=days)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE expires_at BETWEEN ? AND ? AND warned_3d = 0",
                (now.isoformat(), limit.isoformat())
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_expiring_soon error: %s", e)
        return []


async def mark_warned(user_id: int) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                "UPDATE subscriptions SET warned_3d = 1 WHERE user_id = ?", (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.error("mark_warned error: %s", e)


async def delete_subscription(user_id: int) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                "DELETE FROM subscriptions WHERE user_id = ?", (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.error("delete_subscription error: %s", e)


async def log_intruder_kicked(user_id: int, username: str) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                "INSERT INTO stats (event, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
                ("intruder_kicked", user_id, username, datetime.now().isoformat())
            )
            await db.commit()
    except Exception as e:
        logger.error("log_intruder_kicked error: %s", e)


async def get_intruder_log() -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM stats WHERE event = 'intruder_kicked' ORDER BY created_at DESC LIMIT 20"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_intruder_log error: %s", e)
        return []


async def get_stats() -> dict:
    try:
        now     = datetime.now().isoformat()
        limit3d = (datetime.now() + timedelta(days=3)).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            async with db.execute("SELECT COUNT(*) FROM subscriptions") as cur:
                total_subs = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE expires_at > ?", (now,)
            ) as cur:
                active_subs = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE expires_at BETWEEN ? AND ?",
                (now, limit3d)
            ) as cur:
                expiring_soon = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM codes WHERE is_active = 1") as cur:
                active_codes = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM codes") as cur:
                total_codes = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM stats WHERE event = 'intruder_kicked'"
            ) as cur:
                total_kicked = (await cur.fetchone())[0]
        return {
            "total_subs":    total_subs,
            "active_subs":   active_subs,
            "expiring_soon": expiring_soon,
            "active_codes":  active_codes,
            "total_codes":   total_codes,
            "total_kicked":  total_kicked,
        }
    except Exception as e:
        logger.error("get_stats error: %s", e)
        return {}
