"""
database.py — Capa de datos SQLite con conexión persistente
Guarda data.db en /data (volumen persistente Railway) o directorio actual.
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.environ.get("DB_DIR", "."), "data.db")

# ── Conexión persistente (una sola conexión reutilizada en todo el proceso) ───
_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
        _conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,   # python-telegram-bot usa threading internamente
        )
        _conn.row_factory = sqlite3.Row
        # Optimizaciones de rendimiento SQLite
        _conn.execute("PRAGMA journal_mode=WAL")       # escrituras no bloquean lecturas
        _conn.execute("PRAGMA synchronous=NORMAL")     # más rápido, suficientemente seguro
        _conn.execute("PRAGMA cache_size=-8000")       # 8 MB de caché en memoria
        _conn.execute("PRAGMA temp_store=MEMORY")      # tablas temporales en RAM
        _conn.execute("PRAGMA foreign_keys=ON")
        logger.info("✅ Conexión SQLite abierta en %s", DB_PATH)
    return _conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS codes (
            code        TEXT PRIMARY KEY,
            days        INTEGER NOT NULL,
            max_uses    INTEGER NOT NULL,
            used_times  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            created_by  INTEGER NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            first_name  TEXT,
            code        TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1,
            notified_3d INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_subs_user    ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subs_expires ON subscriptions(expires_at);
        CREATE INDEX IF NOT EXISTS idx_subs_active  ON subscriptions(is_active);
    """)
    conn.commit()
    logger.info("✅ DB lista en %s", DB_PATH)


# ── Codes ─────────────────────────────────────────────────────────────────────

def create_code(code: str, days: int, max_uses: int, admin_id: int) -> bool:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO codes (code,days,max_uses,created_at,created_by) VALUES (?,?,?,?,?)",
            (code.upper(), days, max_uses, _now(), admin_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_code(code: str) -> Optional[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM codes WHERE code=? AND is_active=1", (code.upper(),)
    ).fetchone()


def use_code(code: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE codes SET used_times=used_times+1 WHERE code=?", (code.upper(),))
    conn.commit()


def deactivate_code(code: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE codes SET is_active=0 WHERE code=?", (code.upper(),))
    conn.commit()


def list_codes(only_active: bool = True) -> list:
    q = "SELECT * FROM codes" + (" WHERE is_active=1" if only_active else "") + " ORDER BY created_at DESC"
    return get_conn().execute(q).fetchall()


# ── Subscriptions ─────────────────────────────────────────────────────────────

def create_subscription(user_id, username, first_name, code, days) -> str:
    expires = _now_dt() + timedelta(days=days)
    exp_str = expires.isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO subscriptions (user_id,username,first_name,code,started_at,expires_at) VALUES (?,?,?,?,?,?)",
        (user_id, username or "", first_name or "", code.upper(), _now(), exp_str),
    )
    conn.commit()
    return exp_str


def get_active_subscription(user_id: int) -> Optional[sqlite3.Row]:
    return get_conn().execute(
        "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 ORDER BY expires_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def renew_subscription(sub_id: int, extra_days: int) -> str:
    conn = get_conn()
    row  = conn.execute("SELECT expires_at FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    current = datetime.fromisoformat(row["expires_at"])
    base    = max(current, _now_dt())
    new_exp = (base + timedelta(days=extra_days)).isoformat()
    conn.execute(
        "UPDATE subscriptions SET expires_at=?, notified_3d=0, is_active=1 WHERE id=?",
        (new_exp, sub_id),
    )
    conn.commit()
    return new_exp


def deactivate_subscription(user_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=? AND is_active=1", (user_id,))
    conn.commit()


def get_expiring_soon(days: int = 3) -> list:
    cutoff = (_now_dt() + timedelta(days=days)).isoformat()
    return get_conn().execute(
        "SELECT * FROM subscriptions WHERE is_active=1 AND notified_3d=0 AND expires_at<=? AND expires_at>=?",
        (cutoff, _now()),
    ).fetchall()


def get_expired_active() -> list:
    return get_conn().execute(
        "SELECT * FROM subscriptions WHERE is_active=1 AND expires_at<?", (_now(),)
    ).fetchall()


def mark_notified(sub_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE subscriptions SET notified_3d=1 WHERE id=?", (sub_id,))
    conn.commit()


def mark_expired(sub_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE subscriptions SET is_active=0 WHERE id=?", (sub_id,))
    conn.commit()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    conn = get_conn()
    return {
        "total_users":   conn.execute("SELECT COUNT(DISTINCT user_id) FROM subscriptions").fetchone()[0],
        "active_users":  conn.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active=1").fetchone()[0],
        "total_codes":   conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0],
        "active_codes":  conn.execute("SELECT COUNT(*) FROM codes WHERE is_active=1").fetchone()[0],
        "uses_today":    conn.execute("SELECT COUNT(*) FROM subscriptions WHERE started_at>=date('now')").fetchone()[0],
        "expiring_soon": conn.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND expires_at<=datetime('now','+3 days')").fetchone()[0],
    }


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)

def _now() -> str:
    return _now_dt().isoformat()
