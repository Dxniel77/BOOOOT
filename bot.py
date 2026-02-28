"""
database.py — VIP Bot · Capa de datos async (SQLite + WAL)
Versión final con todas las funciones necesarias.
"""

import asyncio
import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_DIR  = os.getenv("DB_DIR", ".")
DB_PATH = os.path.join(DB_DIR, "vip_bot.db")


# ──────────────────────────────────────────────────────────────
# CONEXIÓN
# ──────────────────────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

async def init_db():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _init_db_sync)

def _init_db_sync():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            added_by    INTEGER,
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS codes (
            code        TEXT PRIMARY KEY,
            days        INTEGER NOT NULL,
            max_uses    INTEGER NOT NULL,
            used_count  INTEGER DEFAULT 0,
            note        TEXT,
            expires_at  TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            created_by  INTEGER,
            is_active   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            expiry      TEXT NOT NULL,
            total_days  INTEGER DEFAULT 0,
            renewals    INTEGER DEFAULT 0,
            last_code   TEXT,
            joined_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS blacklist (
            user_id     INTEGER PRIMARY KEY,
            reason      TEXT,
            banned_at   TEXT DEFAULT (datetime('now')),
            banned_by   INTEGER
        );

        CREATE TABLE IF NOT EXISTS free_trials (
            user_id     INTEGER PRIMARY KEY,
            used_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event       TEXT NOT NULL,
            user_id     INTEGER,
            data        TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER NOT NULL,
            action      TEXT NOT NULL,
            target      TEXT,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS broadcast_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message     TEXT NOT NULL,
            filter_type TEXT DEFAULT 'all',
            sent_to     INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            first_name  TEXT,
            subject     TEXT,
            status      TEXT DEFAULT 'open',
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now')),
            closed_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS ticket_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id   INTEGER NOT NULL REFERENCES support_tickets(id),
            sender_id   INTEGER NOT NULL,
            is_admin    INTEGER DEFAULT 0,
            message     TEXT NOT NULL,
            sent_at     TEXT DEFAULT (datetime('now'))
        );
        """)

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

async def run(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


# ──────────────────────────────────────────────────────────────
# ADMINS
# ──────────────────────────────────────────────────────────────
async def get_all_admin_ids() -> list[int]:
    def _f():
        with get_conn() as conn:
            rows = conn.execute("SELECT user_id FROM admins").fetchall()
            return [r["user_id"] for r in rows]
    db_admins = await run(_f)
    main_admin = int(os.getenv("ADMIN_ID", "0"))
    if main_admin and main_admin not in db_admins:
        db_admins.append(main_admin)
    return db_admins

async def add_admin(user_id: int, username: str, first_name: str, added_by: int):
    def _f(u, un, fn, ab):
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admins (user_id,username,first_name,added_by) VALUES (?,?,?,?)",
                (u, un, fn, ab)
            )
    await run(_f, user_id, username, first_name, added_by)

async def remove_admin(user_id: int):
    def _f(u):
        with get_conn() as conn:
            conn.execute("DELETE FROM admins WHERE user_id=?", (u,))
    await run(_f, user_id)

async def list_admins() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute("SELECT * FROM admins ORDER BY added_at ASC").fetchall()
    return await run(_f)


# ──────────────────────────────────────────────────────────────
# CODES
# ──────────────────────────────────────────────────────────────
async def code_exists(code: str) -> bool:
    def _f(c):
        with get_conn() as conn:
            return conn.execute("SELECT 1 FROM codes WHERE code=?", (c,)).fetchone() is not None
    return await run(_f, code)

async def create_code(code: str, days: int, max_uses: int, note: str = "",
                      expires_at: str = None, created_by: int = None):
    def _f(c, d, m, n, e, cb):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO codes (code,days,max_uses,note,expires_at,created_by) VALUES (?,?,?,?,?,?)",
                (c, d, m, n, e, cb)
            )
    await run(_f, code, days, max_uses, note, expires_at, created_by)

async def get_code(code: str) -> Optional[sqlite3.Row]:
    def _f(c):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM codes WHERE code=? AND is_active=1", (c,)).fetchone()
            if not row:
                return None
            if row["expires_at"]:
                exp = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    return None
            return row
    return await run(_f, code)

async def use_code(code: str):
    def _f(c):
        with get_conn() as conn:
            conn.execute("UPDATE codes SET used_count=used_count+1 WHERE code=?", (c,))
    await run(_f, code)

async def deactivate_code(code: str):
    def _f(c):
        with get_conn() as conn:
            conn.execute("UPDATE codes SET is_active=0 WHERE code=?", (c,))
    await run(_f, code)

async def list_codes(active_only: bool = False) -> list:
    def _f(ao):
        with get_conn() as conn:
            q = "SELECT * FROM codes"
            if ao:
                q += " WHERE is_active=1"
            q += " ORDER BY created_at DESC"
            return conn.execute(q).fetchall()
    return await run(_f, active_only)

async def get_active_codes() -> list:
    """Retorna todos los códigos activos no expirados"""
    def _f():
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM codes WHERE is_active=1 AND (expires_at IS NULL OR expires_at > datetime('now')) ORDER BY created_at DESC"
            ).fetchall()
    return await run(_f)

async def delete_code(code: str):
    def _f(c):
        with get_conn() as conn:
            conn.execute("DELETE FROM codes WHERE code=?", (c,))
    await run(_f, code)


# ──────────────────────────────────────────────────────────────
# SUBSCRIPTIONS
# ──────────────────────────────────────────────────────────────
async def get_subscription(user_id: int) -> Optional[sqlite3.Row]:
    def _f(u):
        with get_conn() as conn:
            return conn.execute("SELECT * FROM subscriptions WHERE user_id=?", (u,)).fetchone()
    return await run(_f, user_id)

async def upsert_subscription(user_id: int, username: str, first_name: str,
                               expiry: str, total_days: int, last_code: str):
    def _f(u, un, fn, ex, td, lc):
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO subscriptions (user_id,username,first_name,expiry,total_days,renewals,last_code)
                VALUES (?,?,?,?,?,0,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    expiry=excluded.expiry,
                    total_days=total_days+excluded.total_days,
                    renewals=renewals+1,
                    last_code=excluded.last_code
            """, (u, un, fn, ex, td, lc))
    await run(_f, user_id, username, first_name, expiry, total_days, last_code)

async def delete_subscription(user_id: int):
    def _f(u):
        with get_conn() as conn:
            conn.execute("DELETE FROM subscriptions WHERE user_id=?", (u,))
    await run(_f, user_id)

async def add_days_to_subscription(user_id: int, days: int) -> bool:
    def _f(u, d):
        with get_conn() as conn:
            row = conn.execute("SELECT expiry FROM subscriptions WHERE user_id=?", (u,)).fetchone()
            if not row:
                return False
            from datetime import timedelta
            current = datetime.strptime(row["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            new_exp = max(current, datetime.now(timezone.utc)) + timedelta(days=d)
            conn.execute(
                "UPDATE subscriptions SET expiry=?, total_days=total_days+? WHERE user_id=?",
                (new_exp.strftime("%Y-%m-%d %H:%M:%S"), d, u)
            )
            return True
    return await run(_f, user_id, days)

async def get_all_subscriptions() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute("SELECT * FROM subscriptions ORDER BY expiry DESC").fetchall()
    return await run(_f)

async def get_active_members() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM subscriptions WHERE expiry > datetime('now') ORDER BY expiry ASC"
            ).fetchall()
    return await run(_f)

async def get_expired_members() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM subscriptions WHERE expiry <= datetime('now')"
            ).fetchall()
    return await run(_f)

async def get_expiring_soon(hours: int) -> list:
    def _f(h):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM subscriptions WHERE expiry > datetime('now') "
                "AND expiry <= datetime('now', ? || ' hours')", (str(h),)
            ).fetchall()
    return await run(_f, hours)

async def get_members_by_days_range(min_days: int, max_days: int) -> list:
    def _f(mn, mx):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM subscriptions WHERE expiry > datetime('now') "
                "AND CAST((julianday(expiry) - julianday('now')) AS INTEGER) BETWEEN ? AND ?",
                (mn, mx)
            ).fetchall()
    return await run(_f, min_days, max_days)

async def export_members_csv() -> str:
    def _f():
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, username, first_name, expiry, total_days, renewals, last_code, joined_at "
                "FROM subscriptions ORDER BY joined_at DESC"
            ).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["user_id", "username", "first_name", "expiry", "total_days", "renewals", "last_code", "joined_at"])
        for row in rows:
            writer.writerow([row["user_id"], row["username"] or "", row["first_name"] or "",
                             row["expiry"], row["total_days"], row["renewals"],
                             row["last_code"] or "", row["joined_at"]])
        return output.getvalue()
    return await run(_f)


# ──────────────────────────────────────────────────────────────
# BLACKLIST
# ──────────────────────────────────────────────────────────────
async def is_banned(user_id: int) -> bool:
    def _f(u):
        with get_conn() as conn:
            return conn.execute("SELECT 1 FROM blacklist WHERE user_id=?", (u,)).fetchone() is not None
    return await run(_f, user_id)

async def ban_user(user_id: int, reason: str, banned_by: int):
    def _f(u, r, b):
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO blacklist (user_id,reason,banned_by) VALUES (?,?,?)",
                (u, r, b)
            )
    await run(_f, user_id, reason, banned_by)

async def unban_user(user_id: int):
    def _f(u):
        with get_conn() as conn:
            conn.execute("DELETE FROM blacklist WHERE user_id=?", (u,))
    await run(_f, user_id)

async def get_blacklist() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute("SELECT * FROM blacklist ORDER BY banned_at DESC").fetchall()
    return await run(_f)


# ──────────────────────────────────────────────────────────────
# FREE TRIALS
# ──────────────────────────────────────────────────────────────
async def has_used_trial(user_id: int) -> bool:
    def _f(u):
        with get_conn() as conn:
            return conn.execute("SELECT 1 FROM free_trials WHERE user_id=?", (u,)).fetchone() is not None
    return await run(_f, user_id)

async def mark_trial_used(user_id: int):
    def _f(u):
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO free_trials (user_id) VALUES (?)", (u,))
    await run(_f, user_id)


# ──────────────────────────────────────────────────────────────
# STATS & AUDIT
# ──────────────────────────────────────────────────────────────
async def log_event(event: str, user_id: int = None, data: str = ""):
    def _f(e, u, d):
        with get_conn() as conn:
            conn.execute("INSERT INTO stats (event,user_id,data) VALUES (?,?,?)", (e, u, d))
    await run(_f, event, user_id, data)

async def get_stats_summary() -> dict:
    def _f():
        with get_conn() as conn:
            total    = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
            active   = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE expiry > datetime('now')").fetchone()[0]
            codes_   = conn.execute("SELECT COUNT(*) FROM codes WHERE is_active=1").fetchone()[0]
            banned   = conn.execute("SELECT COUNT(*) FROM blacklist").fetchone()[0]
            trials   = conn.execute("SELECT COUNT(*) FROM free_trials").fetchone()[0]
            new_today= conn.execute("SELECT COUNT(*) FROM subscriptions WHERE date(joined_at)=date('now')").fetchone()[0]
            tickets_open = conn.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'").fetchone()[0]
            expiring_3d  = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE expiry > datetime('now') "
                "AND expiry <= datetime('now', '3 days')"
            ).fetchone()[0]
            admins_count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
            return {
                "total": total, "active": active, "codes": codes_,
                "banned": banned, "trials": trials, "new_today": new_today,
                "tickets_open": tickets_open, "expiring_3d": expiring_3d,
                "admins": admins_count + 1
            }
    return await run(_f)

async def get_user_history(user_id: int) -> list:
    def _f(u):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM stats WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (u,)
            ).fetchall()
    return await run(_f, user_id)

async def audit(admin_id: int, action: str, target: str = "", detail: str = ""):
    def _f(a, ac, t, d):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (admin_id,action,target,detail) VALUES (?,?,?,?)",
                (a, ac, t, d)
            )
    await run(_f, admin_id, action, target, detail)

async def get_audit_log(limit: int = 50) -> list:
    def _f(l):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (l,)
            ).fetchall()
    return await run(_f, limit)


# ──────────────────────────────────────────────────────────────
# BROADCAST LOG
# ──────────────────────────────────────────────────────────────
async def log_broadcast(message: str, filter_type: str, sent_to: int, failed: int):
    def _f(m, ft, s, f):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO broadcast_log (message,filter_type,sent_to,failed) VALUES (?,?,?,?)",
                (m, ft, s, f)
            )
    await run(_f, message, filter_type, sent_to, failed)

async def get_broadcast_history(limit: int = 10) -> list:
    def _f(l):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM broadcast_log ORDER BY created_at DESC LIMIT ?", (l,)
            ).fetchall()
    return await run(_f, limit)


# ──────────────────────────────────────────────────────────────
# SUPPORT TICKETS
# ──────────────────────────────────────────────────────────────
async def create_ticket(user_id: int, username: str, first_name: str, subject: str) -> int:
    def _f(u, un, fn, s):
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO support_tickets (user_id,username,first_name,subject) VALUES (?,?,?,?)",
                (u, un, fn, s)
            )
            return cur.lastrowid
    return await run(_f, user_id, username, first_name, subject)

async def get_ticket(ticket_id: int) -> Optional[sqlite3.Row]:
    def _f(t):
        with get_conn() as conn:
            return conn.execute("SELECT * FROM support_tickets WHERE id=?", (t,)).fetchone()
    return await run(_f, ticket_id)

async def get_user_tickets(user_id: int) -> list:
    def _f(u):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC", (u,)
            ).fetchall()
    return await run(_f, user_id)

async def get_open_tickets() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_tickets WHERE status='open' ORDER BY created_at ASC"
            ).fetchall()
    return await run(_f)

async def get_all_tickets(limit: int = 30) -> list:
    def _f(l):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM support_tickets ORDER BY updated_at DESC LIMIT ?", (l,)
            ).fetchall()
    return await run(_f, limit)

async def add_ticket_message(ticket_id: int, sender_id: int, message: str, is_admin: bool = False):
    def _f(t, s, m, a):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO ticket_messages (ticket_id,sender_id,message,is_admin) VALUES (?,?,?,?)",
                (t, s, m, int(a))
            )
            conn.execute(
                "UPDATE support_tickets SET updated_at=datetime('now') WHERE id=?", (t,)
            )
    await run(_f, ticket_id, sender_id, message, is_admin)

async def get_ticket_messages(ticket_id: int) -> list:
    def _f(t):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY sent_at ASC", (t,)
            ).fetchall()
    return await run(_f, ticket_id)

async def close_ticket(ticket_id: int):
    def _f(t):
        with get_conn() as conn:
            conn.execute(
                "UPDATE support_tickets SET status='closed', closed_at=datetime('now') WHERE id=?", (t,)
            )
    await run(_f, ticket_id)

async def reopen_ticket(ticket_id: int):
    def _f(t):
        with get_conn() as conn:
            conn.execute(
                "UPDATE support_tickets SET status='open', closed_at=NULL WHERE id=?", (t,)
            )
    await run(_f, ticket_id)


# ──────────────────────────────────────────────────────────────
# RANKING
# ──────────────────────────────────────────────────────────────
async def get_ranking(limit: int = 10) -> list:
    def _f(l):
        with get_conn() as conn:
            return conn.execute(
                "SELECT user_id, username, first_name, total_days, joined_at "
                "FROM subscriptions ORDER BY total_days DESC LIMIT ?", (l,)
            ).fetchall()
    return await run(_f, limit)
