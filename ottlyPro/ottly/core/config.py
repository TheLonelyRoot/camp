import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Env:
    MAIN_BOT_TOKEN: str = os.getenv("MAIN_BOT_TOKEN", "")
    MAIN_BOT_USERNAME: str = os.getenv("MAIN_BOT_USERNAME", "")

    LOGIN_BOT_TOKEN: str = os.getenv("LOGIN_BOT_TOKEN", "")
    LOGIN_BOT_USERNAME: str = os.getenv("LOGIN_BOT_USERNAME", "")

    ADMIN_BOT_TOKEN: str = os.getenv("ADMIN_BOT_TOKEN", "")

    LOG_BOT_TOKEN: str = os.getenv("LOG_BOT_TOKEN", "")
    LOG_BOT_USERNAME: str = os.getenv("LOG_BOT_USERNAME", "")

    ADMIN_LOG_BOT_TOKEN: str = os.getenv("ADMIN_LOG_BOT_TOKEN", "")

    JOIN1_CHAT: str = os.getenv("JOIN1_CHAT", "")
    JOIN1_URL: str = os.getenv("JOIN1_URL", "")
    JOIN2_CHAT: str = os.getenv("JOIN2_CHAT", "")
    JOIN2_URL: str = os.getenv("JOIN2_URL", "")

    PRIVACY_URL: str = os.getenv("PRIVACY_URL", "https://example.com/privacy")
    TOS_URL: str = os.getenv("TOS_URL", "https://example.com/terms")
    HOW_TO_API: str = os.getenv("HOW_TO_API_LINK", "https://core.telegram.org/api/obtaining_api_id")
    HOW_TO_HASH: str = os.getenv("HOW_TO_HASH_LINK", "https://core.telegram.org/api/obtaining_api_id")
    BOT_DISPLAY_NAME: str = os.getenv("BOT_DISPLAY_NAME", "TrafficCore bot")
    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "trafficoresupportbot")
    BUY_PREMIUM_USERNAME: str = os.getenv("BUY_PREMIUM_USERNAME", "TrafficCorePay")

    PREMIUM_PRICE_USD: float = float(os.getenv("PREMIUM_PRICE_USD", "5"))
    PREMIUM_DISCOUNT_TEXT: str = os.getenv("PREMIUM_DISCOUNT_TEXT", "10% off")
    PREMIUM_MONTHS_LABEL: str = os.getenv("PREMIUM_MONTHS_LABEL", "month")

    NONPREM_LAST_NAME: str = os.getenv("NONPREM_LAST_NAME", "A9B4N : adbot - via @A9B4NBot 🚀")
    NONPREM_BIO: str = os.getenv("NONPREMIUM_BIO", "🤖 Powered by @A9B4NBot — Free Auto Ad Sender 🚀")

    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")

    SESSIONS_DIR: str = os.getenv("SESSIONS_DIR", "./sessions")
    DB_PATH: str = os.getenv("DB_PATH", "./ottly.db")

    API_ID_DEFAULT: int = int(os.getenv("API_ID_DEFAULT", "0"))
    API_HASH_DEFAULT: str = os.getenv("API_HASH_DEFAULT", "")

    ASSIST_USERNAME: str = os.getenv("ASSIST_USERNAME", "TrafficCoreAssist")

    ENV_AD_MESSAGE: str = os.getenv("ENV_AD_MESSAGE", (
        "✨ Boost Your Reach with @a9b4nbottokens_bot!\n"
        "💬 Distribute your ads automatically — no need to send each message manually.\n"
        "🎯 Promote your products faster, easier, and 100% FREE!"
    ))

    LOGS_DIR: str = os.getenv("LOGS_DIR", "./logs")
    EXCEL_PATH: str = os.getenv("EXCEL_PATH", "./logs/admin_forward_logs.xlsx")
    CREATOR_USERNAME: str = os.getenv("CREATOR_USERNAME", "mrnol")
    FOUNDER_USERNAME: str = os.getenv("FOUNDER_USERNAME", "a9b4n")
    BACKUP_DIR: str = os.getenv("BACKUP_DIR", "./logs/backups")

ENV = Env()
os.makedirs(ENV.SESSIONS_DIR, exist_ok=True)
os.makedirs(ENV.LOGS_DIR, exist_ok=True)
os.makedirs(ENV.BACKUP_DIR, exist_ok=True)
