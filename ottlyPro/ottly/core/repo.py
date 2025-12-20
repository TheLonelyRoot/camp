import json
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from .db import with_conn

@with_conn
def get_cfg(conn, key: str, default=None):
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    return json.loads(row[0]) if (row and row[0] is not None) else default

@with_conn
def set_cfg(conn, key: str, value: Any):
    c = conn.cursor()
    c.execute(
        "INSERT INTO config (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value))
    )

@with_conn
def ensure_user(conn, user_id: int, first_name: str, username: Optional[str]):
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, first_name, username) VALUES (?,?,?)",
                  (user_id, first_name or "", username or ""))
    else:
        c.execute("UPDATE users SET first_name=?, username=? WHERE user_id=?",
                  (first_name or "", username or "", user_id))

@with_conn
def get_user_field(conn, user_id: int, field: str, default=None):
    c = conn.cursor()
    c.execute(f"SELECT {field} FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else default

@with_conn
def set_user_field(conn, user_id: int, field: str, value: Any):
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))

@with_conn
def user_by_username(conn, handle: str) -> Optional[Tuple[int, str]]:
    c = conn.cursor()
    h = handle.lstrip("@").strip()
    c.execute("SELECT user_id, username FROM users WHERE LOWER(username)=LOWER(?)", (h,))
    return c.fetchone()

@with_conn
def is_banned(conn, user_id: int) -> bool:
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return bool(row and row[0])

@with_conn
def get_ban_row(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT reason, ban_type, until_utc, created_at FROM bans WHERE user_id=?", (user_id,))
    return c.fetchone()

@with_conn
def set_ban(conn, user_id: int, reason: str, ban_type: str, until_utc: Optional[str]):
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
    c.execute(
        "INSERT INTO bans (user_id, reason, ban_type, until_utc, created_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason, ban_type=excluded.ban_type, until_utc=excluded.until_utc, created_at=excluded.created_at",
        (user_id, reason, ban_type, until_utc, datetime.utcnow().isoformat())
    )

@with_conn
def unban(conn, user_id: int):
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM bans WHERE user_id=?", (user_id,))

@with_conn
def upsert_live_log_sub(conn, user_id: int, chat_id: int):
    c = conn.cursor()
    c.execute(
        "INSERT INTO live_log_subs (user_id, chat_id) VALUES (?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id",
        (user_id, chat_id)
    )

@with_conn
def get_live_log_chat(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT chat_id FROM live_log_subs WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

@with_conn
def list_sessions(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT id, phone, session_path, is_active FROM sessions WHERE user_id=? ORDER BY id DESC", (user_id,))
    return c.fetchall()

@with_conn
def add_session(conn, user_id: int, phone: str, path: str):
    c = conn.cursor()
    c.execute("INSERT INTO sessions (user_id, phone, session_path, is_active, created_at) VALUES (?,?,?,?,?)",
              (user_id, phone, path, 1, datetime.utcnow().isoformat()))

@with_conn
def get_session_path(conn, session_id: int):
    c = conn.cursor()
    c.execute("SELECT session_path FROM sessions WHERE id=?", (session_id,))
    row = c.fetchone()
    return row[0] if row else None

@with_conn
def get_first_session_path(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT session_path FROM sessions WHERE user_id=? ORDER BY id ASC LIMIT 1", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

@with_conn
def insert_campaign(conn, user_id: int, session_id: int, primary_link: str, links: list[str], interval: int, mode: str, selected: list[int]):
    c = conn.cursor()
    c.execute("""INSERT INTO campaigns (user_id, session_id, campaign_link, campaign_links, interval_sec, group_mode, selected_groups, is_running)
                 VALUES (?,?,?,?,?,?,?,0)""",
              (user_id, session_id, primary_link, json.dumps(links), interval, mode, json.dumps(selected)))

@with_conn
def get_latest_campaign(conn, user_id: int, session_id: int):
    c = conn.cursor()
    c.execute("""SELECT id, campaign_link, campaign_links, interval_sec, group_mode, selected_groups, is_running
                 FROM campaigns WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 1""",
              (user_id, session_id))
    return c.fetchone()

@with_conn
def get_latest_campaign_any(conn, user_id: int):
    c = conn.cursor()
    c.execute("""SELECT id, campaign_link, campaign_links, interval_sec, group_mode, selected_groups, is_running
                 FROM campaigns WHERE user_id=? ORDER BY id DESC LIMIT 1""", (user_id,))
    return c.fetchone()

@with_conn
def set_campaign_running(conn, campaign_id: int, running: int):
    c = conn.cursor()
    c.execute("UPDATE campaigns SET is_running=? WHERE id=?", (running, campaign_id))

@with_conn
def campaigns_running_all(conn):
    c = conn.cursor()
    c.execute("SELECT user_id, session_id FROM campaigns WHERE is_running=1")
    return c.fetchall()

@with_conn
def premium_active(conn, user_id: int) -> bool:
    c = conn.cursor()
    c.execute("SELECT is_premium, premium_until FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        return False
    is_prem, until = row
    if not is_prem:
        return False
    if until:
        try:
            return datetime.fromisoformat(until) > datetime.utcnow()
        except Exception:
            return True
    return True

@with_conn
def premium_until(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

@with_conn
def set_premium_months(conn, user_id:int, months:int, price:float):
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING", (user_id,))
    until = datetime.utcnow() + timedelta(days=30*months)
    c.execute("UPDATE users SET is_premium=1, premium_until=?, plan_label='Premium' WHERE user_id=?", (until.isoformat(), user_id))
    c.execute("INSERT INTO transactions (user_id, amount, currency, plan_label, created_at) VALUES (?,?,?,?,?)",
              (user_id, price, 'USD', 'Premium', datetime.utcnow().isoformat()))

@with_conn
def remove_premium(conn, user_id: int):
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium=0, premium_until=NULL WHERE user_id=?", (user_id,))

@with_conn
def add_metric(conn, user_id: int, ts_utc: str, username: str, profile_name: str, group_name: str, group_id: int, public_link: str, campaign_link: str, is_env_ad: int):
    c = conn.cursor()
    c.execute("""INSERT INTO message_metrics (user_id, ts_utc, username, profile_name, group_name, group_id, public_link, campaign_link, is_env_ad)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
              (user_id, ts_utc, username, profile_name, group_name, group_id, public_link, campaign_link, is_env_ad))

@with_conn
def bump_counters(conn, user_id: int, env_ad: bool):
    c = conn.cursor()
    c.execute("INSERT INTO user_counters (user_id, total_sent, total_env_ad_sent) VALUES (?,0,0) ON CONFLICT(user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE user_counters SET total_sent = total_sent + 1 WHERE user_id=?", (user_id,))
    if env_ad:
        c.execute("UPDATE user_counters SET total_env_ad_sent = total_env_ad_sent + 1 WHERE user_id=?", (user_id,))

@with_conn
def get_user_counters(conn, user_id: int):
    c = conn.cursor()
    c.execute("SELECT total_sent, total_env_ad_sent FROM user_counters WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return (row[0], row[1]) if row else (0, 0)

@with_conn
def reset_user_env_ads(conn, user_id: int):
    c = conn.cursor()
    c.execute("INSERT INTO user_counters (user_id, total_sent, total_env_ad_sent) VALUES (?,0,0) ON CONFLICT(user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE user_counters SET total_env_ad_sent = 0 WHERE user_id=?", (user_id,))

@with_conn
def reset_user_totals(conn, user_id: int):
    c = conn.cursor()
    c.execute("INSERT INTO user_counters (user_id, total_sent, total_env_ad_sent) VALUES (?,0,0) ON CONFLICT(user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE user_counters SET total_env_ad_sent = 0, total_sent = 0 WHERE user_id=?", (user_id,))

@with_conn
def get_global_counters(conn):
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(total_sent),0), COALESCE(SUM(total_env_ad_sent),0) FROM user_counters")
    row = c.fetchone()
    return row or (0, 0)

@with_conn
def add_payment(conn, user_id: int, amount: int, milestone_label: str, mode: str, txn_id: str):
    c = conn.cursor()
    c.execute("""INSERT INTO payments (user_id, amount, milestone_label, mode, txn_id, paid_at_utc)
                 VALUES (?,?,?,?,?,?)""",
              (user_id, amount, milestone_label, mode, txn_id, datetime.utcnow().isoformat()))
    c.execute("INSERT INTO milestones (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE milestones SET total_paid = total_paid + ? WHERE user_id=?", (amount, user_id))

@with_conn
def get_total_paid(conn, user_id: int) -> int:
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

@with_conn
def list_transactions(conn, limit:int=50):
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, currency, plan_label, created_at FROM transactions ORDER BY id DESC LIMIT ?", (limit,))
    return c.fetchall()

@with_conn
def add_admin(conn, user_id:int, username:str):
    c = conn.cursor()
    c.execute("INSERT INTO admins (user_id, username) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", (user_id, username))
    c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (user_id,))

@with_conn
def remove_admin(conn, user_id:int):
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    c.execute("UPDATE users SET is_admin=0 WHERE user_id=?", (user_id,))

@with_conn
def get_last_hourly_run(conn):
    c = conn.cursor()
    c.execute("SELECT last_run_utc FROM hourly_log_state ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    return row[0] if row else None

@with_conn
def set_last_hourly_run(conn, iso: str):
    c = conn.cursor()
    c.execute("INSERT INTO hourly_log_state (last_run_utc) VALUES (?)", (iso,))
