import os
import io
import csv
import asyncio
import zipfile
import sqlite3
from typing import Any, Dict, Iterable, Optional
from datetime import datetime, timezone
from aiogram.types import FSInputFile
import glob

# --- Paths & folders ---------------------------------------------------------

BASE_DIR = os.path.abspath(os.getcwd())
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

os.makedirs(BACKUPS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# Files/folders to include in periodic backup zip
ENV_PATH = os.path.join(BASE_DIR, ".env")
DB_PATH_DEFAULT = os.path.join(BASE_DIR, "ottly.db")
SESSIONS_DIR_DEFAULT = os.path.join(BASE_DIR, "sessions")

# Runtime admin CSV (used by append_admin_log_row)
ADMIN_RUNTIME_CSV = os.path.join(REPORTS_DIR, "admin_runtime_log.csv")

# Event-style CSV (for live runtime messages)
ADMIN_EVENTS_CSV = os.path.join(REPORTS_DIR, 'admin_events_log.csv')

ADMIN_RUNTIME_HEADERS = [
    "Time stamp",
    "Username",
    "users Profile name",
    "Group name",
    "Group Id",
    "Public group link",
    "group campaign link",
]


# --- Helpers ----------------------------------------------------------------

def _fmt_ts_local(ts_iso_or_dt) -> str:
    """
    Takes ISO str or datetime and returns 'DD/MM/YYYY HH:MM:SS TZ'.
    If conversion fails, use UTC now.
    """
    if isinstance(ts_iso_or_dt, datetime):
        dt = ts_iso_or_dt
    else:
        try:
            dt = datetime.fromisoformat(str(ts_iso_or_dt).replace("Z", "+00:00"))
        except Exception:
            dt = datetime.utcnow().replace(tzinfo=timezone.utc)

    try:
        local_dt = dt.astimezone()
    except Exception:
        local_dt = dt

    return local_dt.strftime("%d/%m/%Y %H:%M:%S %Z")


def _zip_backup(out_zip_path: str, env_path: str, db_path: str, sessions_dir: str):
    """
    Create a zip containing .env, ottly.db and all *.session files under sessions/.
    """
    with zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # .env
        if env_path and os.path.exists(env_path):
            zf.write(env_path, arcname=".env")
        # ottly.db
        if db_path and os.path.exists(db_path):
            zf.write(db_path, arcname="ottly.db")
        # sessions/*.session
        if sessions_dir and os.path.isdir(sessions_dir):
            for root, _, files in os.walk(sessions_dir):
                for fname in files:
                    if fname.endswith(".session"):
                        full = os.path.join(root, fname)
                        arc = os.path.relpath(full, BASE_DIR)
                        zf.write(full, arcname=arc)


def _safe_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def _select_rows(conn: sqlite3.Connection, table_name: str, limit: int | None = None):
    """
    Selects * from table_name if it exists. Returns (cols, rows) or ([], []).
    """
    if not _safe_table_exists(conn, table_name):
        return [], []
    try:
        cur = conn.execute(
            f"SELECT * FROM {table_name}" + ("" if limit is None else f" LIMIT {int(limit)}")
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return cols, rows
    except Exception:
        return [], []


# --- CSV build from DB (periodic) -------------------------------------------

def build_logs_csv(db_path: str, out_csv_path: str):
    """
    Build Excel-friendly CSV with exact columns:
    'Time stamp','Username','users Profile name','Group name','Group Id','Public group link','group campaign link'

    Data is sourced primarily from 'message_metrics' (if exists).
    Falls back gracefully (writes header only) when logs are unavailable.
    """
    headers = ADMIN_RUNTIME_HEADERS[:]
    rows_out: list[list[str]] = []

    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(headers)
        return

    try:
        cols, rows = _select_rows(conn, "message_metrics", limit=None)
        if cols:
            idx = {c: i for i, c in enumerate(cols)}

            def get(field_names: Iterable[str]) -> str:
                for fn in field_names:
                    if fn in idx:
                        val = r[idx[fn]]
                        return "" if val is None else str(val)
                return ""

            for r in rows:
                ts_raw = get(["sent_at_utc", "sent_at", "created_at"])
                username = get(["username", "user_name", "tg_username"])
                profile = get(["profile_name", "account_name", "first_last"])
                group_name = get(["group_name", "chat_title", "dialog_name"])
                group_id = get(["group_id", "chat_id"])
                public_link = get(["public_group_link", "group_link", "group_public_link"])
                camp_link = get(["campaign_link", "source_link", "post_link"])

                rows_out.append([
                    _fmt_ts_local(ts_raw),
                    username,
                    profile,
                    group_name,
                    group_id,
                    public_link,
                    camp_link,
                ])
        # If the table is absent we just emit header only.

    finally:
        try:
            conn.close()
        except Exception:
            pass

    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows_out)


# --- NEW: runtime admin log appender (used by forwards.py) ------------------

def append_admin_log_row(
    *args,
    **kwargs,
) -> str:
    """
    Append a single log row to reports/admin_runtime_log.csv with header:

        Time stamp | Username | users Profile name | Group name | Group Id | Public group link | group campaign link

    Accepts either positional:
        (timestamp, username, profile_name, group_name, group_id, public_link, campaign_link)

    Or keyword fields with any of these names:
        timestamp / sent_at_utc / sent_at / created_at
        username / user_name / tg_username
        profile_name / account_name / first_last / name
        group_name / chat_title / dialog_name
        group_id / chat_id
        public_group_link / group_link / group_public_link / public_link
        campaign_link / source_link / post_link

    Returns the path to the CSV file.
    """
    # Ensure directory & header exist
    file_path = ADMIN_RUNTIME_CSV
    need_header = not os.path.exists(file_path)

    # Normalize inputs
    if args and not kwargs:
        # Positional mode
        ts, uname, prof, gname, gid, glink, clink = (list(args) + [""] * 7)[:7]
        ts_nice = _fmt_ts_local(ts)
    else:
        # Keyword mode
        d: Dict[str, Any] = dict(kwargs)

        def pick(keys: Iterable[str], default: str = "") -> str:
            for k in keys:
                if k in d and d[k] is not None:
                    return str(d[k])
            return default

        ts_raw = pick(["timestamp", "sent_at_utc", "sent_at", "created_at", "time", "ts"])
        ts_nice = _fmt_ts_local(ts_raw)
        uname = pick(["username", "user_name", "tg_username"])
        prof = pick(["profile_name", "account_name", "first_last", "name"])
        gname = pick(["group_name", "chat_title", "dialog_name"])
        gid = pick(["group_id", "chat_id"])
        glink = pick(["public_group_link", "group_link", "group_public_link", "public_link"])
        clink = pick(["campaign_link", "source_link", "post_link"])

    # Write row
    try:
        with open(file_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if need_header:
                w.writerow(ADMIN_RUNTIME_HEADERS)
            w.writerow([ts_nice, uname, prof, gname, gid, glink, clink])
    except Exception:
        # If we can’t write for any reason, we fail silently to avoid crashing send loops.
        pass

    return file_path


# --- One-shot & periodic jobs sent to admin log bot -------------------------

async def send_excel_snapshot_now(admin_log_bot, admin_user_id: int, db_path: str | None = None):
    """
    On startup, send only the runtime admin CSV.
    """
    try:
        await admin_log_bot.send_document(
            admin_user_id,
            FSInputFile(ADMIN_RUNTIME_CSV, filename=os.path.basename(ADMIN_RUNTIME_CSV)),
            caption="📊 Admin runtime log (CSV)"
        )
    except Exception:
        pass


async def excel_20min_job(admin_log_bot, admin_user_id: int, db_path: str | None = None):
    """
    Every 30 minutes, send runtime admin CSV + runtime events CSV + live log file.
    """
    while True:
        try:
            # Admin runtime structured CSV
            await admin_log_bot.send_document(
                admin_user_id,
                FSInputFile(ADMIN_RUNTIME_CSV, filename=os.path.basename(ADMIN_RUNTIME_CSV)),
                caption="📊 Admin runtime log (CSV)"
            )
        except Exception:
            pass
        try:
            # Event-style CSV from live logs
            await admin_log_bot.send_document(
                admin_user_id,
                FSInputFile(ADMIN_EVENTS_CSV, filename=os.path.basename(ADMIN_EVENTS_CSV)),
                caption="🧾 Admin EVENTS log (CSV)"
            )
        except Exception:
            pass
        try:
            # Append the raw text log too
            live_log_path = os.path.join(REPORTS_DIR, 'live_runtime.log')
            if os.path.exists(live_log_path):
                await admin_log_bot.send_document(
                    admin_user_id,
                    FSInputFile(live_log_path, filename='live_runtime.log'),
                    caption="📝 Raw live log"
                )
        except Exception:
            pass
        await asyncio.sleep(30 * 60)

# --- Helpers to build a single merged backup zip (.env + ALL DBs + ALL sessions) ---
def _find_db_files(base_dir: str) -> list[str]:
    found = []
    for pat in ["**/*.db", "**/*.sqlite", "**/*.sqlite3"]:
        found.extend(glob.glob(os.path.join(base_dir, pat), recursive=True))
    return sorted(set(found))

def _zip_backup_all(out_zip: str, base_dir: str, env_path: str | None, sessions_dir: str | None):
    os.makedirs(os.path.dirname(out_zip), exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # .env
        if env_path and os.path.exists(env_path):
            z.write(env_path, arcname=".env")
        # All DB files
        for dbf in _find_db_files(base_dir):
            try:
                arc = os.path.relpath(dbf, base_dir)
            except Exception:
                arc = os.path.basename(dbf)
            z.write(dbf, arcname=f"db/{arc}")
        # Sessions tree
        if sessions_dir and os.path.isdir(sessions_dir):
            for root, _, files in os.walk(sessions_dir):
                for name in files:
                    if name.endswith(".session") or name.endswith(".session-journal") or name.endswith(".json"):
                        fp = os.path.join(root, name)
                        arc = os.path.relpath(fp, sessions_dir)
                        z.write(fp, arcname=f"sessions/{arc}")
    return out_zip

async def zip_backup_20min_job(admin_log_bot, admin_user_id: int,
                               env_path: str | None = None,
                               db_path: str | None = None,
                               sessions_dir: str | None = None):
    """
    Every 30 minutes, create/overwrite a single merged backup zip named
    'ottly_backup_merged.zip' and send it to the admin log bot.
    Contents: .env (if present) + ALL DBs + ALL sessions.
    """
    env_path = env_path or ENV_PATH
    sessions_dir = sessions_dir or SESSIONS_DIR_DEFAULT
    base_dir = BASE_DIR
    const_zip_name = "ottly_backup_merged.zip"
    out_zip = os.path.join(BACKUPS_DIR, const_zip_name)
    while True:
        try:
            _zip_backup_all(out_zip, base_dir, env_path, sessions_dir)
            await asyncio.wait_for(
                admin_log_bot.send_document(
                    admin_user_id,
                    FSInputFile(out_zip, filename=const_zip_name),
                    caption="🗂️ Merged backup (.env + ALL DBs + sessions) — every 30 min"
                ), timeout=45
            )
        except Exception:
            pass
        await asyncio.sleep(30 * 60)


def append_admin_event_row(text: str, *, ts: str | None = None) -> str:
    """Append a generic runtime event to admin_events_log.csv with columns: Time stamp | Event"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    need_header = not os.path.exists(ADMIN_EVENTS_CSV)
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    with open(ADMIN_EVENTS_CSV, 'a', newline='', encoding='utf-8') as fh:
        import csv as _csv
        w = _csv.writer(fh)
        if need_header:
            w.writerow(['Time stamp', 'Event'])
        w.writerow([_fmt_ts_local(ts), text])
    return ADMIN_EVENTS_CSV
