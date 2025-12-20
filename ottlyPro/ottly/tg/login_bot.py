import re
import asyncio
from aiogram import Router, F, Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from telethon.sessions import StringSession
from telethon import TelegramClient, errors, functions

from ..core.config import ENV
from ..core.repo import (
    ensure_user,
    list_sessions,
    upsert_live_log_sub,
    add_session,
    get_session_path,
    premium_active,
)
from .keyboards import otp_keyboard, main_menu_kb  # we will not auto-open Ads Manager from main bot
# (User will tap the inline button that opens ?start=ads so Ads Manager opens exactly once.)

rt_login = Router()
LOGIN_STATE = {}

def login_menu_text_kb():
    text = f"<b>Connect Telegram to TrafficCore 📲</b>"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="🔐 Log In (TrafficCore)", callback_data="login_begin")
    kb.button(text="➕ Add Account [TrafficCore Premium]", callback_data="login_add_premium")
    kb.row(
        InlineKeyboardButton(text="🛑 Terminate Account", callback_data="login_terminate"),
        InlineKeyboardButton(text="📇 My TrafficCore Accounts", callback_data="login_list")
    )
    kb.row(InlineKeyboardButton(text="❓How TrafficCore Works", url="https://t.me/trafficoresupportbot?start=help"))
    return text, kb.as_markup()

@rt_login.message(CommandStart())
async def login_start(m: Message):
    ensure_user(m.from_user.id, m.from_user.first_name, m.from_user.username)
    upsert_live_log_sub(m.from_user.id, m.chat.id)
    text, kb = login_menu_text_kb()
    await m.answer(text, reply_markup=kb, disable_web_page_preview=True)

@rt_login.callback_query(F.data.in_(("login_back","noop")))
async def login_back_any(cq: CallbackQuery):
    text, kb = login_menu_text_kb()
    try:
        await cq.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except:
        await cq.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await cq.answer()


@rt_login.callback_query(F.data == "login_begin")
async def login_begin(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    if (not premium_active(uid)) and len(sessions) >= 1:
        price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🚀 Buy TrafficCore Premium", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
        kb.button(text="🔙 Back", callback_data="login_back")
        login_bot_username = getattr(ENV, "LOGIN_BOT_USERNAME", None) or "TrafficCoreLoginBot"
        await cq.message.answer(
            f"<b>Premium active.</b> Add accounts via <b>@{login_bot_username}</b>",
            reply_markup=kb.as_markup()
        )
        return await cq.answer()

    LOGIN_STATE[uid] = {"stage": "api_id"}
    # TrafficCore step-based guidance (modern format)
    await cq.message.answer(
        """🔐 <b>Connect Account — Step 1/4</b>
        <b>Send your API ID</b> (digits only).

        <b>ℹ️ How to get it:</b> <a href=\"https://t.me/TrafficCoreGuide/6\">Tutorial</a>
        <b>ℹ️ Link:</b> <a href=\"https://core.telegram.org/api/obtaining_api_id\">core.telegram.org/api/obtaining_api_id</a>
        <b>Example:</b> <code>123456</code>""",
        disable_web_page_preview=True
    )
    await cq.answer()

@rt_login.callback_query(F.data == "login_add_premium")
async def login_add_premium(cq: CallbackQuery):
    await login_begin(cq)

@rt_login.callback_query(F.data == "login_terminate")
async def login_terminate(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    if not sessions:
        await cq.message.answer("No accounts to terminate."); return await cq.answer()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for sid, phone, *_ in sessions:
        kb.row(
            InlineKeyboardButton(text=f"🛑 {phone}", callback_data=f"term:{sid}")
        )
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="login_back"))
    await cq.message.answer("Select an account to terminate:", reply_markup=kb.as_markup())
    await cq.answer()

@rt_login.callback_query(F.data.startswith("term:"))
async def do_terminate(cq: CallbackQuery):
    uid = cq.from_user.id
    from ..features.campaigns import RUNNING_TASKS
    sid = int(cq.data.split(":")[1])
    t = RUNNING_TASKS.pop((uid, sid), None)
    if t and not t.cancelled(): t.cancel()

    path = get_session_path(sid)
    if path:
        from ..telethon.client import client_from_session_file
        try:
            client = await client_from_session_file(path)
            try: await client.log_out()
            except Exception: pass
            await client.disconnect()
        except Exception: pass
        import os
        try: os.remove(path)
        except Exception: pass

    from ..core.db import db
    con = db(); cur = con.cursor()
    cur.execute("DELETE FROM sessions WHERE id=?", (sid,))
    con.commit(); con.close()
    await cq.message.answer("✅ Terminated and removed.")
    await login_back_any(cq)

@rt_login.message(F.text.regexp(re.compile(r"^\d{4,}$")) & F.func(lambda m: LOGIN_STATE.get(m.from_user.id, {}).get("stage") == "api_id"))
async def login_catch_api_id(m: Message):
    uid = m.from_user.id
    st = LOGIN_STATE.get(uid)
    st["api_id"] = int(m.text.strip())
    st["stage"] = "api_hash"
    # TrafficCore step-based guidance (modern format)
    await m.answer(
        "🔐 <b>Connect Account — Step 2/4</b>\n"
        "Send your <b>API HASH</b> (letters & numbers).\n\n"
        "Looks like: <code>a1b2c3d4e5f6a1b2c3d4e5f6</code>",
        disable_web_page_preview=True
    )

@rt_login.message(F.text.regexp(re.compile(r"^[0-9a-fA-F]{16,64}$")) & F.func(lambda m: LOGIN_STATE.get(m.from_user.id, {}).get("stage") == "api_hash"))
async def login_catch_api_hash(m: Message):
    uid = m.from_user.id
    st = LOGIN_STATE.get(uid)
    st["api_hash"] = m.text.strip()
    st["stage"] = "phone"
    await m.answer(
        "🔐 <b>Connect Account — Step 3/4</b>\n"
        "Send your <b>Phone Number</b> with country code.\n"
        "Example: <code>+447911123456</code>"
    )

@rt_login.message(F.text.regexp(re.compile(r"^\+\d{6,15}$")) & F.func(lambda m: LOGIN_STATE.get(m.from_user.id, {}).get("stage") == "phone"))
async def login_catch_phone(m: Message):
    uid = m.from_user.id
    st = LOGIN_STATE.get(uid)
    phone = m.text.strip()
    st["phone"] = phone

    client = TelegramClient(StringSession(), st["api_id"], st["api_hash"])
    await client.connect()
    try:
        await client.send_code_request(phone)
    except errors.FloodWaitError as fw:
        await m.answer(f"Flood wait: retry in {fw.seconds} seconds."); await client.disconnect(); return
    except Exception as e:
        await m.answer(f"Code request failed: {e}"); await client.disconnect(); return

    st["client"] = client
    st["stage"] = "code"
    msg = await m.answer(
        f"<b>📨 Verification Code (Step 4/4)</b>\nPhone: {phone}\n\n"
        f"Code: <code>_ _ _ _ _</code>\n"
        "Continue using the keypad below.",
        reply_markup=otp_keyboard()
    )
    st["otp_msg_id"] = msg.message_id
    LOGIN_STATE[uid] = st

@rt_login.callback_query(F.data.startswith("otp:"))
async def otp_handler(cq: CallbackQuery):
    uid = cq.from_user.id
    st = LOGIN_STATE.get(uid)
    if not st or st.get("stage") != "code": return await cq.answer()
    action = cq.data.split(":")[1]
    code = st.get("otp","")

    if action.isdigit() and len(code) < 5: code += action
    elif action == "bk" and code: code = code[:-1]
    elif action == "cl": code = ""
    st["otp"] = code; LOGIN_STATE[uid] = st

    def fmt(code: str) -> str:
        filled = list(code) + ["_"]*(5-len(code))
        return " ".join(filled[:5])

    try:
        await cq.message.edit_text(
            f"<b>📨 Verification Code (Step 4/4)</b>\nPhone: {st['phone']}\n\n"
            f"Code: <code>{fmt(code)}</code>\n"
            "Continue using the keypad below.",
            reply_markup=otp_keyboard()
        )
    except Exception: pass

    async def try_sign_in():
        client: TelegramClient = st["client"]
        try:
            await client.sign_in(st["phone"], code)
        except errors.SessionPasswordNeededError:
            st["stage"] = "2fa"; st["twofa_attempts"] = st.get("twofa_attempts", 0); LOGIN_STATE[uid] = st
            try:
                await cq.message.edit_text("<b>🔒 Two-Step Verification Enabled</b>\n\nPlease enter your Telegram cloud password to continue.")
            except Exception: pass
            return
        except errors.PhoneCodeInvalidError:
            st["otp"] = ""; LOGIN_STATE[uid] = st
            await cq.message.edit_text(
                f"<b>📨 Verification Code (Step 4/4)</b>\nPhone: {st['phone']}\n\n"
                "❌ Code invalid. Try again.\n"
                f"Code: <code>{fmt('')}</code>",
                reply_markup=otp_keyboard()
            ); return
        except errors.PhoneCodeExpiredError:
            st["otp"] = ""; LOGIN_STATE[uid] = st
            await cq.message.edit_text(
                f"<b>📨 Verification Code (Step 4/4)</b>\nPhone: {st['phone']}\n\n"
                "⌛ Code expired. Use /start to request a new one."
            )
            await st["client"].disconnect(); LOGIN_STATE.pop(uid, None); return
        except Exception as e:
            await cq.message.answer(f"Code error: {e}"); return
        await finalize_login(uid, cq.message.chat.id, st, cq.bot)

    if len(code) == 5 or action == "ok":
        await try_sign_in()
    await cq.answer()

@rt_login.message((F.text | F.caption) & F.func(lambda m: LOGIN_STATE.get(m.from_user.id, {}).get("stage") == "2fa"))
async def login_catch_2fa(m: Message):
    uid = m.from_user.id
    st = LOGIN_STATE.get(uid)
    pwd = m.text if (m.text is not None) else (m.caption if (m.caption is not None) else "")
    waiting_msg = await m.answer("⏳ Processing 2FA…")
    client: TelegramClient = st["client"]

    try:
        await asyncio.wait_for(client.sign_in(password=pwd), timeout=25)
    except Exception as e:
        await waiting_msg.edit_text(f"❌ 2FA error: {e}\nPlease enter your password again:"); return

    try:
        authorized = await client.is_user_authorized()
    except Exception:
        authorized = False
    if not authorized:
        await waiting_msg.edit_text("❌ Login not completed. Please re-enter your Telegram cloud password exactly."); return

    st["stage"] = "finalizing"; LOGIN_STATE[uid] = st
    await waiting_msg.edit_text("✅ 2FA accepted. Finalizing login…")
    await finalize_login(uid, m.chat.id, st, m.bot)

async def finalize_login(uid:int, chat_id:int, st:dict, login_bot):
    client: TelegramClient = st["client"]
    try:
        if not await client.is_user_authorized():
            return
        session_str = client.session.save()

        from ..telethon.sessions import telethon_session_filepath, write_string_session
        path = telethon_session_filepath(uid, st["phone"])
        write_string_session(path, session_str)
        add_session(uid, st["phone"], path)

        # Ensure the "🚀Here Send Campaign" channel exists
        try:
            ch = None
            async for d in client.iter_dialogs():
                if d.is_channel and d.name.strip() == "🚀Here Send Campaign":
                    ch = d.entity; break
            if not ch:
                res = await client(functions.channels.CreateChannelRequest(
                    title="🚀Here Send Campaign",
                    about="Auto-created by TrafficCore bot after successful login.",
                    megagroup=False, for_import=False
                ))
                ch = res.chats[0]
                try:
                    uname = f"SetupTrafficCoreAds{uid}"
                    await client(functions.channels.UpdateUsernameRequest(ch, uname))
                except Exception:
                    pass
        except Exception:
            pass

    finally:
        try: await client.disconnect()
        except Exception: pass

    # 1) Send MAIN BOT "Main menu:" once to ensure the persistent Reply Keyboard is visible
    try:
        main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await main_bot.send_message(uid, "Main menu:", reply_markup=main_menu_kb())
    except Exception:
        pass

    # 2) In LOGIN BOT, show single redirect button to Ads Manager (no duplicate opens)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Live Status Bot", url="https://t.me/a9b4nlog_bot")]
        ]
    )
    await login_bot.send_message(chat_id, "✅ Successfully logged in!", reply_markup=kb)

    LOGIN_STATE.pop(uid, None)

@rt_login.callback_query(F.data == "login_list")
async def login_list(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for sid, phone, *_ in sessions:
        kb.row(InlineKeyboardButton(text=phone, callback_data="noop"))
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="login_back"))
    await cq.message.answer("📇 My Accounts", reply_markup=kb.as_markup()); await cq.answer()
