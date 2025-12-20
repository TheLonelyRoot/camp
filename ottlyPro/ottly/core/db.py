import sqlite3
from contextlib import closing
from typing import Callable
from .config import ENV

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(ENV.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _column_exists(conn, table: str, col: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def init_db():
    with closing(db()) as conn, conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            agreed INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0,
            premium_until TEXT,
            plan_label TEXT DEFAULT 'Premium',
            global_active INTEGER DEFAULT 0,
            last_chat_id INTEGER
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone TEXT,
            session_path TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id INTEGER,
            campaign_link TEXT,
            interval_sec INTEGER,
            group_mode TEXT,
            selected_groups TEXT,
            is_running INTEGER DEFAULT 0,
            campaign_links TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY, reason TEXT, ban_type TEXT, until_utc TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS live_log_subs (user_id INTEGER PRIMARY KEY, chat_id INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            currency TEXT DEFAULT 'USD',
            plan_label TEXT,
            created_at TEXT
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS message_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ts_utc TEXT,
            username TEXT,
            profile_name TEXT,
            group_name TEXT,
            group_id INTEGER,
            public_link TEXT,
            campaign_link TEXT,
            is_env_ad INTEGER DEFAULT 0
        )""")

        # --- Migrations for existing DBs ---
        # Add campaign_link
        if not _column_exists(conn, "message_metrics", "campaign_link"):
            c.execute("ALTER TABLE message_metrics ADD COLUMN campaign_link TEXT")
        # Add is_env_ad
        if not _column_exists(conn, "message_metrics", "is_env_ad"):
            c.execute("ALTER TABLE message_metrics ADD COLUMN is_env_ad INTEGER DEFAULT 0")

        c.execute("""
        CREATE TABLE IF NOT EXISTS user_counters (
            user_id INTEGER PRIMARY KEY,
            total_sent INTEGER DEFAULT 0,
            total_env_ad_sent INTEGER DEFAULT 0
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS milestones (
            user_id INTEGER PRIMARY KEY,
            m20k INTEGER DEFAULT 0,
            m35k INTEGER DEFAULT 0,
            m100k INTEGER DEFAULT 0,
            total_paid INTEGER DEFAULT 0
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            milestone_label TEXT,
            mode TEXT,
            txn_id TEXT,
            paid_at_utc TEXT
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS runtime_flags (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS hourly_log_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_run_utc TEXT
        )""")

        conn.commit()

def with_conn(fn: Callable):
    def wrapper(*args, **kwargs):
        with closing(db()) as conn, conn:
            return fn(conn, *args, **kwargs)
    return wrapper

init_db()
