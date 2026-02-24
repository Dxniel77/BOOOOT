"""
╔══════════════════════════════════════════════╗
║          DX VIP BOT — database.py            ║
║     Capa de datos completa | SQLite + WAL    ║
╚══════════════════════════════════════════════╝
"""

import aiosqlite
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(os.getenv("DB_DIR", "/data"), "bot.db")


# ══════════════════════════════════════════════
# CONEXIÓN BASE
# ══════════════════════════════════════════════

async def get_connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=-64000")
    conn.row_factory = aiosqlite.Row
    return conn


# ══════════════════════════════════════════════
# INICIALIZACIÓN
# ══════════════════════════════════════════════

async def init_db() -> None:
    async with await get_connection() as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code        TEXT PRIMARY KEY,
                days        INTEGER NOT NULL,
                max_uses    INTEGER NOT NULL DEFAULT 1,
                used_count  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1,
                note        TEXT,
                created_by  INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                expires_at  TEXT NOT NULL,
                code_used   TEXT,
                invite_link TEXT,
                warned_3d   INTEGER NOT NULL DEFAULT 0,
                warned_1d   INTEGER NOT NULL DEFAULT 0,
                total_days  INTEGER NOT NULL DEFAULT 0,
                renewals    INTEGER NOT NULL DEFAULT 0,
                referred_by INTEGER,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                reason      TEXT,
                banned_at   TEXT NOT NULL,
                banned_by   INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id     INTEGER NOT NULL,
                referred_id     INTEGER NOT NULL UNIQUE,
                bonus_days      INTEGER NOT NULL DEFAULT 0,
                bonus_given     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS free_trials (
                user_id     INTEGER PRIMARY KEY,
                used_at     TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id    INTEGER NOT NULL,
                action      TEXT NOT NULL,
                target_id   INTEGER,
                detail      TEXT,
                created_at  TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id    INTEGER NOT NULL,
                message     TEXT NOT NULL,
                sent_count  INTEGER NOT NULL DEFAULT 0,
                fail_count  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_subs_expires   ON subscriptions(expires_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_stats_event    ON stats(event)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_stats_created  ON stats(created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_admin    ON audit_log(admin_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ref_referrer   ON referrals(referrer_id)")

        await db.commit()
    logger.info("✅ DB inicializada en %s", DB_PATH)


# ══════════════════════════════════════════════
# CÓDIGOS
# ══════════════════════════════════════════════

async def code_exists(code: str) -> bool:
    async with await get_connection() as db:
        async with db.execute("SELECT 1 FROM codes WHERE code=?", (code,)) as cur:
            return await cur.fetchone() is not None


async def create_code(code: str, days: int, max_uses: int,
                      note: str | None = None, created_by: int | None = None) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with await get_connection() as db:
            await db.execute(
                "INSERT INTO codes (code,days,max_uses,used_count,created_at,is_active,note,created_by) "
                "VALUES (?,?,?,0,?,1,?,?)",
                (code, days, max_uses, now, note, created_by),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def get_code(code: str) -> aiosqlite.Row | None:
    async with await get_connection() as db:
        async with db.execute("SELECT * FROM codes WHERE code=?", (code,)) as cur:
            return await cur.fetchone()


async def increment_code_usage(code: str) -> None:
    async with await get_connection() as db:
        await db.execute("UPDATE codes SET used_count=used_count+1 WHERE code=?", (code,))
        await db.execute(
            "UPDATE codes SET is_active=0 WHERE code=? AND used_count>=max_uses", (code,)
        )
        await db.commit()


async def list_codes(only_active: bool = False) -> list:
    async with await get_connection() as db:
        q = "SELECT * FROM codes"
        if only_active:
            q += " WHERE is_active=1"
        q += " ORDER BY created_at DESC"
        async with db.execute(q) as cur:
            return await cur.fetchall()


async def deactivate_code(code: str) -> None:
    async with await get_connection() as db:
        await db.execute("UPDATE codes SET is_active=0 WHERE code=?", (code,))
        await db.commit()


async def delete_code(code: str) -> None:
    async with await get_connection() as db:
        await db.execute("DELETE FROM codes WHERE code=?", (code,))
        await db.commit()


async def get_codes_stats() -> dict:
    async with await get_connection() as db:
        async with db.execute("SELECT COUNT(*) FROM codes") as c:
            total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM codes WHERE is_active=1") as c:
            active = (await c.fetchone())[0]
        async with db.execute("SELECT SUM(used_count) FROM codes") as c:
            row = await c.fetchone()
            uses = row[0] or 0
    return {"total": total, "active": active, "inactive": total - active, "total_uses": uses}


# ══════════════════════════════════════════════
# SUSCRIPCIONES
# ══════════════════════════════════════════════

async def get_subscription(user_id: int) -> aiosqlite.Row | None:
    async with await get_connection() as db:
        async with db.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone()


async def upsert_subscription(user_id: int, username: str | None, full_name: str,
                               expires_at: datetime, code_used: str, invite_link: str,
                               days: int, referred_by: int | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    exp = expires_at.isoformat()
    async with await get_connection() as db:
        async with db.execute(
            "SELECT total_days, renewals FROM subscriptions WHERE user_id=?", (user_id,)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            await db.execute(
                """UPDATE subscriptions SET username=?,full_name=?,expires_at=?,code_used=?,
                   invite_link=?,warned_3d=0,warned_1d=0,
                   total_days=total_days+?,renewals=renewals+1,updated_at=?
                   WHERE user_id=?""",
                (username, full_name, exp, code_used, invite_link, days, now, user_id),
            )
        else:
            await db.execute(
                """INSERT INTO subscriptions
                   (user_id,username,full_name,expires_at,code_used,invite_link,
                    warned_3d,warned_1d,total_days,renewals,referred_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,0,0,?,0,?,?,?)""",
                (user_id, username, full_name, exp, code_used, invite_link, days, referred_by, now, now),
            )
        await db.commit()


async def add_days_to_subscription(user_id: int, extra_days: int) -> datetime | None:
    sub = await get_subscription(user_id)
    if sub is None:
        return None
    old = datetime.fromisoformat(sub["expires_at"])
    if old.tzinfo is None:
        old = old.replace(tzinfo=timezone.utc)
    base = max(old, datetime.now(timezone.utc))
    new_exp = base + timedelta(days=extra_days)
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        await db.execute(
            "UPDATE subscriptions SET expires_at=?,warned_3d=0,warned_1d=0,"
            "total_days=total_days+?,renewals=renewals+1,updated_at=? WHERE user_id=?",
            (new_exp.isoformat(), extra_days, now, user_id),
        )
        await db.commit()
    return new_exp


async def mark_warned_3d(user_id: int) -> None:
    async with await get_connection() as db:
        await db.execute("UPDATE subscriptions SET warned_3d=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def mark_warned_1d(user_id: int) -> None:
    async with await get_connection() as db:
        await db.execute("UPDATE subscriptions SET warned_1d=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def delete_subscription(user_id: int) -> None:
    async with await get_connection() as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))
        await db.commit()


async def get_active_subscriptions() -> list:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM subscriptions WHERE expires_at>? ORDER BY expires_at ASC", (now,)
        ) as cur:
            return await cur.fetchall()


async def get_expired_subscriptions() -> list:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM subscriptions WHERE expires_at<=?", (now,)
        ) as cur:
            return await cur.fetchall()


async def get_expiring_soon(days: int = 3, warned_field: str = "warned_3d") -> list:
    now = datetime.now(timezone.utc)
    limit = (now + timedelta(days=days)).isoformat()
    now_iso = now.isoformat()
    field = warned_field if warned_field in ("warned_3d", "warned_1d") else "warned_3d"
    async with await get_connection() as db:
        async with db.execute(
            f"SELECT * FROM subscriptions WHERE expires_at>? AND expires_at<=? AND {field}=0",
            (now_iso, limit),
        ) as cur:
            return await cur.fetchall()


async def get_all_subscriptions() -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM subscriptions ORDER BY created_at DESC"
        ) as cur:
            return await cur.fetchall()


async def search_user(query: str) -> list:
    async with await get_connection() as db:
        rows = []
        if query.lstrip("-").isdigit():
            async with db.execute(
                "SELECT * FROM subscriptions WHERE user_id=?", (int(query),)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            p = f"%{query}%"
            async with db.execute(
                "SELECT * FROM subscriptions WHERE username LIKE ? OR full_name LIKE ?", (p, p)
            ) as cur:
                rows = await cur.fetchall()
        return rows


async def count_subscriptions() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        async with db.execute("SELECT COUNT(*) FROM subscriptions") as c:
            total = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE expires_at>?", (now,)
        ) as c:
            active = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE expires_at<=?", (now,)
        ) as c:
            expired = (await c.fetchone())[0]
        async with db.execute("SELECT SUM(total_days) FROM subscriptions") as c:
            row = await c.fetchone()
            total_days = row[0] or 0
        async with db.execute("SELECT SUM(renewals) FROM subscriptions") as c:
            row = await c.fetchone()
            total_renewals = row[0] or 0
    return {
        "total": total, "active": active, "expired": expired,
        "total_days": total_days, "total_renewals": total_renewals,
    }


# ══════════════════════════════════════════════
# BLACKLIST
# ══════════════════════════════════════════════

async def add_to_blacklist(user_id: int, username: str | None,
                            full_name: str | None, reason: str | None,
                            banned_by: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        await db.execute(
            """INSERT OR REPLACE INTO blacklist
               (user_id,username,full_name,reason,banned_at,banned_by)
               VALUES (?,?,?,?,?,?)""",
            (user_id, username, full_name, reason, now, banned_by),
        )
        await db.commit()


async def remove_from_blacklist(user_id: int) -> bool:
    async with await get_connection() as db:
        cur = await db.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def is_blacklisted(user_id: int) -> bool:
    async with await get_connection() as db:
        async with db.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None


async def get_blacklist() -> list:
    async with await get_connection() as db:
        async with db.execute("SELECT * FROM blacklist ORDER BY banned_at DESC") as cur:
            return await cur.fetchall()


# ══════════════════════════════════════════════
# REFERIDOS
# ══════════════════════════════════════════════

async def create_referral(referrer_id: int, referred_id: int, bonus_days: int = 7) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with await get_connection() as db:
            await db.execute(
                "INSERT INTO referrals (referrer_id,referred_id,bonus_days,bonus_given,created_at) "
                "VALUES (?,?,?,0,?)",
                (referrer_id, referred_id, bonus_days, now),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def get_referral_count(referrer_id: int) -> int:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (referrer_id,)
        ) as cur:
            return (await cur.fetchone())[0]


async def get_pending_bonuses(referrer_id: int) -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM referrals WHERE referrer_id=? AND bonus_given=0", (referrer_id,)
        ) as cur:
            return await cur.fetchall()


async def mark_bonus_given(referral_id: int) -> None:
    async with await get_connection() as db:
        await db.execute("UPDATE referrals SET bonus_given=1 WHERE id=?", (referral_id,))
        await db.commit()


async def get_referrals_by_referrer(referrer_id: int) -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM referrals WHERE referrer_id=? ORDER BY created_at DESC",
            (referrer_id,),
        ) as cur:
            return await cur.fetchall()


# ══════════════════════════════════════════════
# PRUEBA GRATIS
# ══════════════════════════════════════════════

async def has_used_free_trial(user_id: int) -> bool:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT 1 FROM free_trials WHERE user_id=?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def mark_free_trial_used(user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        await db.execute(
            "INSERT OR IGNORE INTO free_trials (user_id,used_at) VALUES (?,?)", (user_id, now)
        )
        await db.commit()


# ══════════════════════════════════════════════
# AUDITORÍA
# ══════════════════════════════════════════════

async def audit(admin_id: int, action: str,
                target_id: int | None = None, detail: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with await get_connection() as db:
            await db.execute(
                "INSERT INTO audit_log (admin_id,action,target_id,detail,created_at) "
                "VALUES (?,?,?,?,?)",
                (admin_id, action, target_id, detail, now),
            )
            await db.commit()
    except Exception as exc:
        logger.error("audit error: %s", exc)


async def get_audit_log(limit: int = 30) -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()


# ══════════════════════════════════════════════
# ESTADÍSTICAS
# ══════════════════════════════════════════════

async def log_event(event: str, user_id: int | None = None,
                    detail: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        async with await get_connection() as db:
            await db.execute(
                "INSERT INTO stats (event,user_id,detail,created_at) VALUES (?,?,?,?)",
                (event, user_id, detail, now),
            )
            await db.commit()
    except Exception as exc:
        logger.error("log_event error: %s", exc)


async def get_stats_summary() -> dict:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT event, COUNT(*) as cnt FROM stats GROUP BY event ORDER BY cnt DESC"
        ) as cur:
            rows = await cur.fetchall()
    return {r["event"]: r["cnt"] for r in rows}


async def get_recent_events(limit: int = 20) -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM stats ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()


async def get_stats_last_days(days: int = 7) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with await get_connection() as db:
        async with db.execute(
            """SELECT substr(created_at,1,10) as day, COUNT(*) as cnt
               FROM stats WHERE created_at>=? GROUP BY day ORDER BY day ASC""",
            (since,),
        ) as cur:
            return await cur.fetchall()


async def get_new_users_last_days(days: int = 7) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with await get_connection() as db:
        async with db.execute(
            """SELECT substr(created_at,1,10) as day, COUNT(*) as cnt
               FROM subscriptions WHERE created_at>=? GROUP BY day ORDER BY day ASC""",
            (since,),
        ) as cur:
            return await cur.fetchall()


# ══════════════════════════════════════════════
# BROADCAST LOG
# ══════════════════════════════════════════════

async def log_broadcast(admin_id: int, message: str,
                         sent: int, failed: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        await db.execute(
            "INSERT INTO broadcast_log (admin_id,message,sent_count,fail_count,created_at) "
            "VALUES (?,?,?,?,?)",
            (admin_id, message[:500], sent, failed, now),
        )
        await db.commit()


async def get_broadcast_history(limit: int = 10) -> list:
    async with await get_connection() as db:
        async with db.execute(
            "SELECT * FROM broadcast_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()
