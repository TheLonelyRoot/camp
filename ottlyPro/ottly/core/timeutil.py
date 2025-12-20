from datetime import datetime
import pytz
from .config import ENV

TZ = pytz.timezone(ENV.TIMEZONE)

def now_local() -> datetime:
    return datetime.now(TZ)

def ts_log() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M:%S %Z")

def format_local_dt(utc_iso: str) -> str:
    if not utc_iso:
        return "Unknown"
    dt = datetime.fromisoformat(utc_iso)
    if dt.tzinfo is None:
        import pytz as _p
        dt = _p.utc.localize(dt)
    return dt.astimezone(TZ).strftime("%d %b %Y | %I:%M %p")

def format_local_hms(utc_iso: str) -> str:
    if not utc_iso:
        return now_local().strftime("%d/%m/%Y %H:%M:%S %Z")
    dt = datetime.fromisoformat(utc_iso)
    if dt.tzinfo is None:
        import pytz as _p
        dt = _p.utc.localize(dt)
    return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S %Z")

def format_duration(from_iso: str, to_dt: datetime | None = None) -> str:
    if not from_iso:
        return "0 minutes"
    start = datetime.fromisoformat(from_iso)
    end = to_dt or datetime.utcnow()
    delta = end - start
    mins = int(delta.total_seconds() // 60)
    hours = mins // 60
    rem = mins % 60
    if hours > 0:
        return f"{hours} hour {rem} minutes" if hours == 1 else f"{hours} hours {rem} minutes"
    return f"{mins} minutes"
