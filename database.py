"""
database.py — DX VIP Bot · Capa de datos async (SQLite + WAL)
Tablas: codes, subscriptions, blacklist, free_trials,
        stats, audit_log, broadcast_log,
        support_tickets, ticket_messages, ruleta_log
"""

import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_DIR = os.getenv("DB_DIR", ".")
DB_PATH = os.path.join(DB_DIR, "dx_vip.db")

# ──────────────────────────────────────────────────────────────
# INIT
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
        CREATE TABLE IF NOT EXISTS codes (
            code        TEXT PRIMARY KEY,
            days        INTEGER NOT NULL,
            max_uses    INTEGER NOT NULL,
            used_count  INTEGER DEFAULT 0,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
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

        CREATE TABLE IF NOT EXISTS ruleta_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            days_won    INTEGER NOT NULL,
            played_at   TEXT DEFAULT (datetime('now'))
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
# CODES
# ──────────────────────────────────────────────────────────────
async def code_exists(code: str) -> bool:
    def _f(c):
        with get_conn() as conn:
            return conn.execute("SELECT 1 FROM codes WHERE code=?", (c,)).fetchone() is not None
    return await run(_f, code)

async def create_code(code: str, days: int, max_uses: int, note: str = ""):
    def _f(c, d, m, n):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO codes (code,days,max_uses,note) VALUES (?,?,?,?)",
                (c, d, m, n)
            )
    await run(_f, code, days, max_uses, note)

async def get_code(code: str) -> Optional[sqlite3.Row]:
    def _f(c):
        with get_conn() as conn:
            return conn.execute("SELECT * FROM codes WHERE code=? AND is_active=1", (c,)).fetchone()
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

async def list_codes() -> list:
    def _f():
        with get_conn() as conn:
            return conn.execute("SELECT * FROM codes ORDER BY created_at DESC").fetchall()
    return await run(_f)

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
            existing = conn.execute("SELECT renewals FROM subscriptions WHERE user_id=?", (u,)).fetchone()
            renewals = (existing["renewals"] + 1) if existing else 0
            conn.execute("""
                INSERT INTO subscriptions (user_id,username,first_name,expiry,total_days,renewals,last_code)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    expiry=excluded.expiry,
                    total_days=excluded.total_days,
                    renewals=renewals+1,
                    last_code=excluded.last_code
            """, (u, un, fn, ex, td, renewals, lc))
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
            conn.execute("UPDATE subscriptions SET expiry=?, total_days=total_days+? WHERE user_id=?",
                         (new_exp.strftime("%Y-%m-%d %H:%M:%S"), d, u))
            return True
    return await run(_f, user_id, days)

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
# STATS
# ──────────────────────────────────────────────────────────────
async def log_event(event: str, user_id: int = None, data: str = ""):
    def _f(e, u, d):
        with get_conn() as conn:
            conn.execute("INSERT INTO stats (event,user_id,data) VALUES (?,?,?)", (e, u, d))
    await run(_f, event, user_id, data)

async def get_stats_summary() -> dict:
    def _f():
        with get_conn() as conn:
            total     = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
            active    = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE expiry > datetime('now')").fetchone()[0]
            codes_    = conn.execute("SELECT COUNT(*) FROM codes WHERE is_active=1").fetchone()[0]
            banned    = conn.execute("SELECT COUNT(*) FROM blacklist").fetchone()[0]
            trials    = conn.execute("SELECT COUNT(*) FROM free_trials").fetchone()[0]
            new_today = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE date(joined_at)=date('now')"
            ).fetchone()[0]
            tickets_open = conn.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE status='open'"
            ).fetchone()[0]
            return {
                "total": total, "active": active, "codes": codes_,
                "banned": banned, "trials": trials, "new_today": new_today,
                "tickets_open": tickets_open
            }
    return await run(_f)

async def get_user_history(user_id: int) -> list:
    def _f(u):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM stats WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (u,)
            ).fetchall()
    return await run(_f, user_id)

# ──────────────────────────────────────────────────────────────
# AUDIT LOG
# ──────────────────────────────────────────────────────────────
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
async def log_broadcast(message: str, sent_to: int, failed: int):
    def _f(m, s, f):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO broadcast_log (message,sent_to,failed) VALUES (?,?,?)",
                (m, s, f)
            )
    await run(_f, message, sent_to, failed)

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
# RULETA
# ──────────────────────────────────────────────────────────────
async def can_play_ruleta(user_id: int) -> bool:
    """True si el usuario NO ha jugado en los últimos 7 días."""
    def _f(u):
        with get_conn() as conn:
            row = conn.execute(
                "SELECT played_at FROM ruleta_log WHERE user_id=? ORDER BY played_at DESC LIMIT 1", (u,)
            ).fetchone()
            if not row:
                return True
            from datetime import timedelta
            last = datetime.strptime(row["played_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - last >= timedelta(days=7)
    return await run(_f, user_id)

async def log_ruleta(user_id: int, days_won: int):
    def _f(u, d):
        with get_conn() as conn:
            conn.execute("INSERT INTO ruleta_log (user_id,days_won) VALUES (?,?)", (u, d))
    await run(_f, user_id, days_won)

async def get_ruleta_history(user_id: int) -> list:
    def _f(u):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM ruleta_log WHERE user_id=? ORDER BY played_at DESC LIMIT 10", (u,)
            ).fetchall()
    return await run(_f, user_id)

# ──────────────────────────────────────────────────────────────
# RANKING (solo admin)
# ──────────────────────────────────────────────────────────────
async def get_ranking(limit: int = 10) -> list:
    """Top miembros por días totales acumulados."""
    def _f(l):
        with get_conn() as conn:
            return conn.execute(
                "SELECT user_id, username, first_name, total_days, joined_at "
                "FROM subscriptions ORDER BY total_days DESC LIMIT ?", (l,)
            ).fetchall()
    return await run(_f, limit)
