from datetime import datetime
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from ..core.config import ENV
from ..core.repo import get_cfg, set_cfg, is_banned, get_ban_row, set_user_field
from ..core.timeutil import format_local_dt, format_duration

# --- Downtime helpers ---
def downtime_active() -> bool:
    return bool(get_cfg("downtime_active", False))

def downtime_started_utc():
    return get_cfg("downtime_started_utc", None)

def downtime_reason():
    return get_cfg("downtime_reason", "Scheduled maintenance / Technical issue")

def set_downtime(active: bool, reason: str | None = None):
    set_cfg("downtime_active", active)
    if active:
        set_cfg("downtime_started_utc", datetime.utcnow().isoformat())
        set_cfg("downtime_reason", reason or "Scheduled maintenance / Technical issue")
    else:
        set_cfg("downtime_started_utc", None)


class BanMiddleware(BaseMiddleware):
    """
    HARD BLOCKER for banned users.
    - Runs on both Dispatcher (outer) and Router (message+callback) levels.
    - If banned: answers callback alert (to close spinner), sends a single notice, then STOPS.
    """
    async def __call__(self, handler, event, data):
        try:
            uid = None
            chat_id = None

            if isinstance(event, Message):
                uid = event.from_user.id if event.from_user else None
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery):
                uid = event.from_user.id if event.from_user else None
                chat_id = event.message.chat.id if event.message else None

            # Owner bypass
            if uid == ENV.OWNER_ID:
                return await handler(event, data)

            # Enforce ban
            if uid and is_banned(uid):
                reason, ban_type, until_iso, created_at = get_ban_row(uid) or ("—", "Permanent", None, None)
                ban_date_local = format_local_dt(created_at) if created_at else format_local_dt(datetime.utcnow().isoformat())

                text = (
                    "<b>⚠️ Access Restricted</b>\n\n"
                    "You’ve been <b>banned</b> by the admin.\n"
                    f"🗓️ <b>Date:</b> {ban_date_local}\n"
                    f"❗ <b>Reason:</b> {reason or '—'}\n\n"
                    f"📩 Need help? Contact <b>@{ENV.ASSIST_USERNAME}</b>"
                )

                bot = data.get("bot")

                # For callback: close spinner with an alert
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("Access Restricted: You are banned.", show_alert=True)
                    except Exception:
                        pass

                if bot and chat_id:
                    try:
                        await bot.send_message(chat_id, text, disable_web_page_preview=True)
                    except Exception:
                        pass

                # DO NOT pass control to handlers
                return

        except Exception:
            # Fail-safe: still block on any middleware error
            return

        # Not banned -> continue
        return await handler(event, data)


class DowntimeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if downtime_active():
                uid = None
                chat_id = None
                if isinstance(event, Message):
                    uid = event.from_user.id if event.from_user else None
                    chat_id = event.chat.id
                elif isinstance(event, CallbackQuery):
                    uid = event.from_user.id if event.from_user else None
                    chat_id = event.message.chat.id if event.message else None

                # Owner bypass
                if uid and uid == ENV.OWNER_ID:
                    return await handler(event, data)

                start_iso = downtime_started_utc()
                reason = downtime_reason()
                started_local = format_local_dt(start_iso) if start_iso else "Unknown"
                duration = f"{format_duration(start_iso)}" if start_iso else "—"

                text = (
                    "🕒 Status: 🔴 Offline\n"
                    f"📅 Downtime Started: {started_local}\n"
                    f"⏳ Duration: {duration}\n"
                    f"📌 Reason: {reason}"
                )

                bot = data.get("bot")
                if bot and chat_id:
                    try:
                        await bot.send_message(chat_id, text, disable_web_page_preview=True)
                    except Exception:
                        pass
                return
        except Exception:
            pass

        return await handler(event, data)


class ChatTrackMiddleware(BaseMiddleware):
    """
    Tracks last_chat_id so we can DM users later if needed.
    """
    async def __call__(self, handler, event, data):
        try:
            uid = None
            chat_id = None
            if isinstance(event, Message):
                uid = event.from_user.id if event.from_user else None
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery):
                uid = event.from_user.id if event.from_user else None
                chat_id = event.message.chat.id if event.message else None

            if uid and chat_id:
                set_user_field(uid, "last_chat_id", chat_id)
        except Exception:
            pass

        return await handler(event, data)
