from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from ..core.repo import ensure_user, upsert_live_log_sub

rt_log = Router()

@rt_log.message(CommandStart())
async def log_start(m: Message):
    """
    Users must /start this bot once so we can DM them logs.
    We store their chat_id keyed by user_id and then only their logs go here.
    """
    ensure_user(m.from_user.id, m.from_user.first_name, m.from_user.username)
    upsert_live_log_sub(m.from_user.id, m.chat.id)
    await m.answer(
        "📈 CAMP RUN live logging enabled for your campaigns.\n\n"
        "You will receive detailed logs for each ad sent while your campaigns are running.\n"
        "Tip: keep this chat unmuted while testing."
    )

@rt_log.message()
async def log_any(m: Message):
    # Any message also refreshes the mapping (handy if user loses history)
    ensure_user(m.from_user.id, m.from_user.first_name, m.from_user.username)
    upsert_live_log_sub(m.from_user.id, m.chat.id)
    await m.answer("✅ Log channel linked. You'll see CAMP RUN live logs for your own campaigns here.")
