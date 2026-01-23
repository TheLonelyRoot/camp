from ..core.timeutil import ts_log
from ..core.repo import get_live_log_chat
from ..features.reporter import append_admin_event_row
from aiogram import Bot

def display_name(ent) -> str:
    name = getattr(ent, "title", None)
    if name: return name
    first = getattr(ent, "first_name", "") or ""
    last = getattr(ent, "last_name", "") or ""
    nm = (first + " " + last).strip()
    return nm or getattr(ent, "username", "Unknown")

def link_to_user(user_obj) -> str:
    uname = getattr(user_obj, "username", None)
    if uname:
        return f'<a href="https://t.me/{uname}">@{uname}</a>'
    return f'<a href="tg://user?id={user_obj.id}">user</a>'

def tme_group_link(group_ent, msg_id:int) -> str:
    uname = getattr(group_ent, "username", None)
    if uname:
        return f"https://t.me/{uname}/{msg_id}"
    gid = str(getattr(group_ent, "id", ""))
    if gid.startswith("-100"):
        gid = gid[4:]
    else:
        gid = gid.lstrip("-")
    return f"https://t.me/c/{gid}/{msg_id}"

async def send_live_log(log_bot: Bot, user_id: int, text: str):
    if not log_bot:
        return
    chat_id = get_live_log_chat(user_id)
    if chat_id:
        try:
            await log_bot.send_message(chat_id, text, disable_web_page_preview=True)
        except Exception:
            pass

def fmt_group_log(status:str, username:str, group_name:str, group_id:int, group_link:str):
    # Improved UI: clearer, more readable log with CAMP RUN branding and clickable username if available
    from ..core.config import ENV
    creator = "CamprunsMains_bot"  # Set your new username here
    user_display = f'<a href="https://t.me/{username}">@{username}</a>' if username else 'Unknown User'
    return (
        f'✅ <b>Ad Sent Successfully</b>\n'
        f'🕒 <b>Time:</b> {ts_log()}\n'
        f'👤 <b>Sender:</b> {user_display}\n'
        f'👥 <b>Group:</b> <b>{group_name}</b>\n'
        f'🆔 <b>Group ID:</b> <code>{group_id}</code>\n'
        f'🔗 <a href="{group_link}">View Ad</a>\n'
        f'🏷️ <b>Status:</b> {status}\n'
        f'🤖 <i>Powered by @CamprunsMains_bot</i>'
    )
