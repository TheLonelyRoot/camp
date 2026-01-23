from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..core.config import ENV

def kb_welcome_gating() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="join", url="https://t.me/+QnMmwA7ISm85OWU5")
    kb.button(text="join", url="https://t.me/+i_k6WzY4DKcwNTY9")
    kb.row(InlineKeyboardButton(text="✅ Agree Terms & Conditions", callback_data="agree_terms"))
    return kb.as_markup()

def kb_ads_manager_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠️ Setup CAMP RUN Campaigns", callback_data="ads_setup")
    kb.row(
        InlineKeyboardButton(text="🚀 Start CAMP RUN Campaign", callback_data="ads_start"),
        InlineKeyboardButton(text="🔴 Stop All CAMP RUN", callback_data="ads_stop_all")
    )
    kb.row(InlineKeyboardButton(text="🕒 CAMP RUN Auto Mode", callback_data="pubads_auto"))
    kb.row(InlineKeyboardButton(text="❓ How to Use CAMP RUN", url="https://t.me/CamprunsAdminss_bot?start=help"))
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_main"))
    return kb.as_markup()

def kb_setup_intervals() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, mins in [
        ("🕒 Every 3 min", 3), ("🕧 Every 5 min", 5), ("🕐 Every 10 min", 10),
        ("🕓 Every 15 min", 15), ("🕕 Every 30 min", 30), ("🕘 Every 1 hours", 60),
        ("🗓️ Daily", 60*24), ("📅 Weekly", 60*24*7)
    ]:
        kb.row(InlineKeyboardButton(text=label, callback_data=f"camp_ivl:{mins}"))
    kb.row(InlineKeyboardButton(text="⏱ Custom interval", callback_data="camp_ivl_custom"))
    return kb.as_markup()

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤Account"), KeyboardButton(text="📣Ads Manager")],
            [KeyboardButton(text="✏️Customize Name"), KeyboardButton(text="🛟Support")],
            [KeyboardButton(text="⭐ Subscriptions")],
            [KeyboardButton(text="📨 Total Messages Sent"), KeyboardButton(text="📊 Ads Message Total Sent")]
        ],
        resize_keyboard=True
    )

def otp_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    rows = [["1","2","3"],["4","5","6"],["7","8","9"],["0","⌫ Back","🧹 Clear"]]
    for r in rows[:-1]:
        kb.row(*(InlineKeyboardButton(text=d, callback_data=f"otp:{d}") for d in r))
    kb.row(
        InlineKeyboardButton(text="0", callback_data="otp:0"),
        InlineKeyboardButton(text="⌫ Back", callback_data="otp:bk"),
        InlineKeyboardButton(text="🧹 Clear", callback_data="otp:cl"),
    )
    kb.row(InlineKeyboardButton(text="✔️ Submit", callback_data="otp:ok"))
    kb.row(InlineKeyboardButton(text=f"📨 Open Telegram (777000)", url="tg://user?id=777000"))
    return kb.as_markup()

def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Stats")],
            [KeyboardButton(text="1) acess of bot"), KeyboardButton(text="2) Ban Members")],
            [KeyboardButton(text="3) Add members for pro"), KeyboardButton(text="4) 📋 Active Subscriptions")],
            [KeyboardButton(text="5) Total Transcations"), KeyboardButton(text="6) Downtime")],
            [KeyboardButton(text="7) Remove Subscription"), KeyboardButton(text="📣 Broadcast")],
            [KeyboardButton(text="💸 Give Payment to User"), KeyboardButton(text="🔎 Users Milestone Check")],
        ],
        resize_keyboard=True
    )

def admin_access_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Add Admin", callback_data="admin_add"),
           InlineKeyboardButton(text="➖ Remove Admin", callback_data="admin_rm"))
    kb.row(InlineKeyboardButton(text="📃 List Admins", callback_data="admin_list"))
    return kb.as_markup()

def ban_manage_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚫 Add Ban", callback_data="ban_add"),
           InlineKeyboardButton(text="✅ Remove Ban", callback_data="ban_rm"))
    kb.row(InlineKeyboardButton(text="📃 List Banned", callback_data="ban_list"))
    return kb.as_markup()

def stats_quick_actions_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="👥 Manage User", callback_data="stats_manage_user"),
        InlineKeyboardButton(text="🚫 Ban Management", callback_data="stats_ban_mgmt")
    )
    return kb.as_markup()

def public_ads_controls_kb(starting: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not starting:
        kb.button(text="▶️ Start Ads", callback_data="pubads_start")
    else:
        kb.button(text="⏹ Stop Ads", callback_data="pubads_stop")
    kb.button(text="🕒 Auto Mode", callback_data="pubads_auto")
    kb.button(text="24/7 Support — DM", url="https://t.me/CamprunsAdminss_bot")
    return kb.as_markup()
