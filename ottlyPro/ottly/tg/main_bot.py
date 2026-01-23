import re
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from ..core.config import ENV
from ..core.repo import ensure_user, get_user_field, set_user_field, list_sessions, premium_active, premium_until, get_live_log_chat, upsert_live_log_sub
from ..core.timeutil import format_local_dt
from .keyboards import kb_welcome_gating, kb_ads_manager_menu, kb_setup_intervals, main_menu_kb, public_ads_controls_kb
from ..features.campaigns import count_all_groups_in_session, insert_campaign, build_groups_markup, start_campaign_for, stop_campaign_for, RUNNING_TASKS, create_env_ad_post_and_link
from ..features.metrics import user_totals_text
from ..telethon.forwards import parse_post_link
from ..telethon.client import client_from_session_file

rt_main = Router()

_AUX = {"log_bot": None}

AUTO_MODE_EXPECTING: set[int] = set()

TIME_RANGE_RE = re.compile(r"^\s*\d{1,2}(:\d{2})?\s*(am|pm)\s*-\s*\d{1,2}(:\d{2})?\s*(am|pm)\s*$", re.IGNORECASE)


def _mins_to_12h(mins: int) -> str:
    mins = mins % (24 * 60)
    h = mins // 60
    m = mins % 60
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {suffix}"


def _parse_time_range_to_minutes(text: str):
    txt = (text or "").strip().lower()
    txt = txt.replace("–", "-")
    if "-" not in txt:
        return None
    left, right = [part.strip() for part in txt.split("-", 1)]

    def _one(side: str):
        s = side
        ampm = None
        if s.endswith("am"):
            ampm = "am"
            s = s[:-2].strip()
        elif s.endswith("pm"):
            ampm = "pm"
            s = s[:-2].strip()
        if ":" in s:
            hh_str, mm_str = s.split(":", 1)
        else:
            hh_str, mm_str = s, "0"
        try:
            hh = int(hh_str)
            mm = int(mm_str)
        except ValueError:
            return None
        if mm < 0 or mm > 59:
            return None
        if ampm:
            if hh < 1 or hh > 12:
                return None
            if ampm == "am":
                hh = 0 if hh == 12 else hh
            else:
                hh = 12 if hh == 12 else hh + 12
        else:
            if hh < 0 or hh > 23:
                return None
        return hh * 60 + mm

    start = _one(left)
    end = _one(right)
    if start is None or end is None:
        return None
    return start, end

def _premium_mode_blocked(uid: int) -> bool:
    from ..core.repo import get_cfg, premium_active
    try:
        on = bool(get_cfg("premium_mode:on", False))
    except Exception:
        on = False
    if not on:
        return False
    if uid == ENV.OWNER_ID:
        return False
    if premium_active(uid):
        return False
    return True


async def _maybe_premium_mode_gate_msg(m: Message) -> bool:
    if not _premium_mode_blocked(m.from_user.id):
        return False
    price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Buy Now", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
    await m.answer(
        f"<b>Go Premium — {price} 🚀</b>\n"
        "\n"
        "<b>Unlock all features:</b>\n"
        "• 👥 <b>Multiple accounts</b> — add and manage more accounts\n"
        "• 💎 <b>Multiple post link</b> — rotate between different posts\n"
        "• ⚡️ <b>Priority high</b> — faster sending & support\n"
        "• 🕒 <b>Auto Mode</b> — run ads only in your chosen hours\n"
        "• 🧵 <b>Forum topics</b> — send in specific topics\n"
        "• ⏱️ <b>Per-group interval</b> — set time interval per group\n"
        "• 😎 <b>Premium emoji support</b> — use premium emoji without Telegram Premium\n"
        "\n"
        "<i>Buy now and unlock everything.</i>",
        reply_markup=kb.as_markup()
    )
    return True

def set_aux_bots(log_bot, _):
    _AUX["log_bot"] = log_bot

@rt_main.message(CommandStart())
async def main_start(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    try:
        await m.answer("👋 Welcome! Loading menu…")
    except Exception:
        pass
    ensure_user(m.from_user.id, m.from_user.first_name, m.from_user.username)
    try:
        bot_username = (await m.bot.get_me()).username
        if bot_username and bot_username.lower() == (ENV.LOG_BOT_USERNAME or "").lower():
            upsert_live_log_sub(m.from_user.id, m.chat.id)
    except Exception:
        pass

    parts = (m.text or "").split(maxsplit=1)
    param = parts[1] if len(parts) > 1 else ""
    agreed = int(get_user_field(m.from_user.id, "agreed", 0) or 0)

    # Always show main menu keyboard first to keep it visible
    if agreed == 1 and param == "ads":
        await m.answer("Main menu:", reply_markup=main_menu_kb())
        await m.answer("🛠️ All ads set up here:", reply_markup=kb_ads_manager_menu(), disable_web_page_preview=True)
        return

    if agreed == 1:
        await m.answer("Main menu:", reply_markup=main_menu_kb())
        return

    text = (
        f"🤖 Welcome to {ENV.BOT_DISPLAY_NAME or 'CAMP RUN bot'} 🚀\n"
        "Easily send & schedule ads across multiple Telegram groups.\n\n"
        "📊 Smart distribution • Reliable delivery\n"
        "📜 No spam, no illegal content — fully compliant with platform rules.\n\n"
        f"👨‍💻 Made by @{ENV.CREATOR_USERNAME or 'mrnol'}\n"
        f"👑 Founder: @{ENV.FOUNDER_USERNAME or 'a9b4n'}\n"
        f"✅ By using this bot, you agree to our <a href=\"{ENV.TOS_URL}\">Terms & Conditions</a>"
    )
    await m.answer(text, reply_markup=kb_welcome_gating(), disable_web_page_preview=True)

@rt_main.callback_query(F.data == "agree_terms")
async def on_agree_terms(cq: CallbackQuery, bot):
    u = cq.from_user
    set_user_field(u.id, "agreed", 1)
    try: await cq.message.delete()
    except: pass
    await bot.send_message(u.id, "Main menu:", reply_markup=main_menu_kb())

@rt_main.message(F.text == "👤Account")
async def account_menu(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    uid = m.from_user.id
    sessions = list_sessions(uid)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if sessions:
        for sid, phone, *_ in sessions:
            builder.row(
                InlineKeyboardButton(text=f"{phone}", callback_data=f"acc_phone:{sid}"),
                InlineKeyboardButton(text="🗑️ Delete", callback_data=f"acc_del:{sid}")
            )
        builder.row(InlineKeyboardButton(text="➕ Add Account [premium]", callback_data="acc_add"))
    else:
        login_username = ENV.LOGIN_BOT_USERNAME or "LoginBot"
        builder.row(InlineKeyboardButton(text="🔐 Log In ↗️", url=f"https://t.me/{login_username}?start=connect"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_main"))
    await m.answer("<b>⚙️ Account Management</b>\n\nManage your Telegram accounts here:", reply_markup=builder.as_markup())

@rt_main.callback_query(F.data.startswith("acc_del:"))
async def acc_delete(cq: CallbackQuery):
    sid = int(cq.data.split(":")[1])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Confirm Delete", callback_data=f"acc_del_yes:{sid}")
    kb.button(text="✖ Cancel", callback_data="back_main")
    await cq.message.answer("Are you sure you want to terminate this device and delete the session?", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data.startswith("acc_del_yes:"))
async def acc_delete_yes(cq: CallbackQuery):
    from ..core.repo import get_session_path
    from ..telethon.client import client_from_session_file
    from ..core.db import db
    uid = cq.from_user.id
    sid = int(cq.data.split(":")[1])
    t = RUNNING_TASKS.pop((uid, sid), None)
    if t and not t.cancelled(): t.cancel()

    path = get_session_path(sid)
    if path:
        try:
            client = await client_from_session_file(path)
            try: await client.log_out()
            except Exception: pass
            await client.disconnect()
        except Exception: pass
        import os
        try: os.remove(path)
        except Exception: pass
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM sessions WHERE id=?", (sid,))
    con.commit(); con.close()

    try: await cq.message.delete()
    except: pass
    await account_menu(await cq.message.answer("Refreshing..."))
    await cq.answer()

@rt_main.callback_query(F.data == "acc_add")
async def acc_add_premium_gate(cq: CallbackQuery):
    if not premium_active(cq.from_user.id):
        price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text=f"🚀 Buy Premium", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
        kb.button(text="OK, got it", callback_data="prem_ok")
        await cq.message.answer(
            f"<b>Go Premium — {price} 🚀</b>\n"
            "Run multiple accounts and unlock premium features.\n"
            "<b>What you get</b>\n"
            "👥 Multiple accounts (manage more brands)\n"
            "💎 Multiple post link (rotate through posts)\n"
            f"⚡ Priority lane: faster sending + top-tier support @{'{ENV.SUPPORT_USERNAME}' if ENV.SUPPORT_USERNAME else 'CamprunsAdminss_bot'}\n"
            "🕒 Auto Mode (schedule daily sending hours)\n"
            "🧵 Forum topics (send in specific topics)\n"
            "⏱ Per-group interval (set time interval per group)\n"
            "😎 Premium emoji support (use premium emoji without Telegram Premium)\n"
            f"Limited offer — upgrade now and save {ENV.PREMIUM_DISCOUNT_TEXT}.",
            reply_markup=kb.as_markup()
        )
        await cq.answer()
    else:
        login_username = ENV.LOGIN_BOT_USERNAME or "LoginBot"
        await cq.message.answer(
            f"Premium active. Add accounts via @{login_username}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Open Login Bot", url=f"https://t.me/{login_username}?start=connect")]
            ])
        )
        await cq.answer()

@rt_main.callback_query(F.data == "prem_ok")
async def prem_ok_main(cq: CallbackQuery):
    try: await cq.message.delete()
    except: pass
    await cq.answer()

@rt_main.message(F.text == "📣Ads Manager")
async def ads_manager(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    await m.answer("🛠️ All ads set up here:", reply_markup=kb_ads_manager_menu())

SETUP_STATE = {}

@rt_main.callback_query(F.data == "ads_setup")
async def ads_setup(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    if not sessions:
        login_username = ENV.LOGIN_BOT_USERNAME or "LoginBot"
        await cq.message.answer(
            "No accounts linked yet. Use the Login bot first.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Open Login Bot", url=f"https://t.me/{login_username}?start=connect")]
            ])
        )
        await cq.answer(); return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for sid, phone, *_ in sessions:
        kb.row(InlineKeyboardButton(text=phone, callback_data=f"setup_pick:{sid}"))
    try:
        await cq.message.edit_text("Select an account to set campaign for:", reply_markup=kb.as_markup())
    except:
        await cq.message.answer("Select an account to set campaign for:", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data.startswith("setup_pick:"))
async def setup_pick(cq: CallbackQuery):
    uid = cq.from_user.id
    sid = int(cq.data.split(":")[1])
    SETUP_STATE[uid] = {"session_id": sid, "step":"ask_link", "links":[]}
    upsell = ""
    if not premium_active(uid):
        upsell = "\n\n💎 Multiple post link — <b>Premium</b> feature. Upgrade to add multiple posts."
    try: await cq.message.delete()
    except: pass
    await cq.message.answer('🚀 Here — Send Campaign\nSend me the <b>post link</b> from your "<b>🚀Here Send Campaign</b>" channel.' + upsell)
    await cq.answer()

@rt_main.message(F.text.regexp(re.compile(r"https?://t\.me/")) & F.func(lambda m: SETUP_STATE.get(m.from_user.id, {}).get("step")=="ask_link"))
async def setup_link_catcher(m: Message):
    uid = m.from_user.id
    st = SETUP_STATE.get(uid)
    peer, msgid = parse_post_link(m.text)
    if not peer:
        await m.answer("That doesn't look like a valid Telegram post link. Try again."); return
    st["links"].append(m.text.strip())
    SETUP_STATE[uid] = st

    if premium_active(uid):
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Add another post link", callback_data="add_link_more")
        kb.button(text="💾 Save links", callback_data="save_links")
        kb.row(InlineKeyboardButton(text="🗑️ Clear all", callback_data="clear_links"))
        await m.answer(
            f"✅ Saved link #{len(st['links'])}.\n"
            f"Current: {len(st['links'])} link(s). Add more or save.",
            reply_markup=kb.as_markup()
        )
    else:
        st["step"] = "ask_tag_mode"
        SETUP_STATE[uid] = st
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🕶️ Hide tag", callback_data="tag_mode:hide")
        kb.button(text="🔗 With tag", callback_data="tag_mode:with")
        await m.answer("✅ Campaign link saved.\nChoose forwarding mode:", reply_markup=kb.as_markup())

@rt_main.callback_query(F.data == "add_link_more")
async def add_link_more(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: return await cq.answer()
    if not premium_active(uid):
        return await cq.answer("💎 Multiple post link is Premium only.", show_alert=True)
    st["step"] = "ask_link"
    SETUP_STATE[uid] = st
    await cq.message.answer("Send next post link:")
    await cq.answer()

@rt_main.callback_query(F.data == "clear_links")
async def clear_links(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: return await cq.answer()
    st["links"] = []
    SETUP_STATE[uid] = st
    await cq.message.answer("Cleared all links. Send a fresh post link:")
    await cq.answer()

@rt_main.callback_query(F.data == "save_links")
async def save_links(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st or not st.get("links"):
        await cq.answer("Add at least one post link.", show_alert=True); 
        return
    # go to tag mode selection first
    st["step"] = "ask_tag_mode"
    SETUP_STATE[uid] = st
    try: await cq.message.delete()
    except: pass
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="🕶️ Hide tag", callback_data="tag_mode:hide")
    kb.button(text="🔗 With tag", callback_data="tag_mode:with")
    await cq.message.answer(
        f"✅ Saved {len(st['links'])} post link(s).\nChoose forwarding mode:",
        reply_markup=kb.as_markup()
    )
    await cq.answer()


@rt_main.callback_query(F.data.startswith("camp_ivl:"))
async def setup_interval(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st or st.get("step") != "ask_interval":
        await cq.answer(); return
    mins = int(cq.data.split(":")[1])
    st["interval"] = mins*60
    st["step"] = "group_choice"
    SETUP_STATE[uid] = st
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ All groups", callback_data="grp_all")
    kb.button(text="🎯 Choose groups", callback_data="grp_choose")
    try: await cq.message.delete()
    except: pass
    await cq.message.answer("📣 Select Group\nChoose where to send your campaign.", reply_markup=kb.as_markup())
    await cq.answer("✅ Time set successfully.")



@rt_main.callback_query(F.data == "camp_ivl_custom")
async def setup_custom_interval(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st or st.get("step") != "ask_interval":
        await cq.answer(); return
    from ..core.repo import premium_active
    if not premium_active(uid):
        await cq.answer("💎 Custom interval is Premium only.", show_alert=True)
        return
    st["step"] = "ask_custom_interval"
    SETUP_STATE[uid] = st
    try: await cq.message.delete()
    except: pass
    await cq.message.answer(
        "Send custom <b>campaign interval</b> in seconds or minutes.\n"
        "Examples: <code>45s</code>, <code>2m</code>."
    )
    await cq.answer()

@rt_main.callback_query(F.data == "grp_all")
async def grp_all(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: await cq.answer(); return
    links = st.get("links", [])
    primary = links[0] if links else ""
    from ..core.repo import get_session_path, insert_campaign
    session_path = get_session_path(st["session_id"])
    if not session_path:
        await cq.message.answer("Session not found."); return await cq.answer()
    total_groups = await count_all_groups_in_session(session_path)
    insert_campaign(uid, st["session_id"], primary, links, st["interval"], "all", [])
    mins = int(st["interval"] // 60)
    try: await cq.message.delete()
    except: pass
    from ..core.repo import get_cfg
    topic_links = get_cfg(f"campaign_topic_links:{uid}", []) or []
    total_topics = len(topic_links)
    await cq.message.answer(f"✅ Setup saved — groups: <b>{total_groups}</b> | topics: <b>{total_topics}</b> | interval: <b>{mins}m</b>.")
    await cq.message.answer("🛠️ All ads set up here:", reply_markup=kb_ads_manager_menu())
    SETUP_STATE.pop(uid, None)
    await cq.answer()

@rt_main.callback_query(F.data == "grp_choose")
async def grp_choose(cq: CallbackQuery):
    uid = cq.from_user.id
    from ..core.repo import get_session_path
    st = SETUP_STATE.get(uid)
    if not st: await cq.answer(); return
    st["mode"] = "choose"
    st.setdefault("selected", set())
    session_path = get_session_path(st["session_id"])
    if not session_path:
        await cq.message.answer("Session not found."); return await cq.answer()
    st["session_path"] = session_path
    text, markup = await build_groups_markup(session_path, st["selected"], page=0)
    st["page"] = 0
    SETUP_STATE[uid] = st
    try: await cq.message.delete()
    except: pass
    sent = await cq.message.answer(text, reply_markup=markup)
    st["picker_msg_id"] = sent.message_id
    SETUP_STATE[uid] = st
    await cq.answer()

@rt_main.callback_query(F.data.startswith("grp_page:"))
async def grp_page(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: return await cq.answer()
    page = int(cq.data.split(":")[1])
    st["page"] = page
    SETUP_STATE[uid] = st
    text, markup = await build_groups_markup(st["session_path"], st["selected"], page=page)
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except:
        await cq.message.edit_reply_markup(reply_markup=markup)
    await cq.answer()

@rt_main.callback_query(F.data.startswith("pickgrp:"))
async def on_pick_group(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: return await cq.answer()
    gid = int(cq.data.split(":")[1])
    st.setdefault("selected", set())
    if gid in st["selected"]:
        st["selected"].remove(gid)
    else:
        st["selected"].add(gid)
    SETUP_STATE[uid] = st
    text, markup = await build_groups_markup(st["session_path"], st["selected"], page=st.get("page",0))
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except:
        await cq.message.edit_reply_markup(reply_markup=markup)
    await cq.answer()

@rt_main.callback_query(F.data == "savegrps")
async def on_save_groups(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid)
    if not st: return await cq.answer()
    selected = sorted(list(st.get("selected", [])))
    links = st.get("links", [])
    primary = links[0] if links else ""
    insert_campaign(uid, st["session_id"], primary, links, st["interval"], "choose", selected)
    try:
        if st.get("picker_msg_id"):
            await cq.bot.delete_message(cq.message.chat.id, st["picker_msg_id"])
    except: pass
    try: await cq.message.delete()
    except: pass
    mins = int(st["interval"] // 60)
    from ..core.repo import get_cfg
    topic_links = get_cfg(f"campaign_topic_links:{uid}", []) or []
    total_topics = len(topic_links)
    await cq.message.answer(f"✅ Setup saved — groups: <b>{len(selected)}</b> | topics: <b>{total_topics}</b> | interval: <b>{mins}m</b>.")
    await cq.message.answer("🛠️ All ads set up here:", reply_markup=kb_ads_manager_menu())
    SETUP_STATE.pop(uid, None)
    await cq.answer()

@rt_main.callback_query(F.data == "ads_start")
async def ads_start(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    if not sessions:
        login_username = ENV.LOGIN_BOT_USERNAME or "LoginBot"
        await cq.message.answer(
            "No accounts linked.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔐 Open Login Bot", url=f"https://t.me/{login_username}?start=connect")]
            ])
        )
        return await cq.answer()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for sid, phone, *_ in sessions:
        kb.row(InlineKeyboardButton(text=phone, callback_data=f"startpick:{sid}"))
    kb.row(InlineKeyboardButton(text="👥 Start for All", callback_data="start_all"))
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text("Select the account to start:", reply_markup=kb.as_markup())
    except:
        await cq.message.answer("Select the account to start:", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data.startswith("startpick:"))
async def start_pick(cq: CallbackQuery):
    uid = cq.from_user.id
    sid = int(cq.data.split(":")[1])
    running = (uid, sid) in RUNNING_TASKS and RUNNING_TASKS[(uid,sid)] and not RUNNING_TASKS[(uid,sid)].cancelled() and not RUNNING_TASKS[(uid,sid)].done()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Live Status", url=f"https://t.me/{ENV.LOG_BOT_USERNAME}")
    if running: kb.button(text="🔴 Stop", callback_data=f"stop_one:{sid}")
    else: kb.button(text="▶️ Start", callback_data=f"go_one:{sid}")
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text("Account selected. Choose an action:", reply_markup=kb.as_markup())
    except:
        await cq.message.answer("Account selected. Choose an action:", reply_markup=kb.as_markup())
        try: await cq.message.delete()
        except: pass
    await cq.answer()

@rt_main.callback_query(F.data.startswith("go_one:"))
async def go_one(cq: CallbackQuery):
    uid = cq.from_user.id
    sid = int(cq.data.split(":")[1])
    try:
        await start_campaign_for(cq.bot, None, _AUX["log_bot"], ENV.OWNER_ID, uid, sid, kb_welcome_gating())
    except Exception as e:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Back", callback_data="back_ads")
        try:
            await cq.message.edit_text(f"❌ Can't start: {e}", reply_markup=kb.as_markup())
        except:
            await cq.message.answer(f"❌ Can't start: {e}")
        return await cq.answer()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Live Status", url=f"https://t.me/{ENV.LOG_BOT_USERNAME}")
    kb.button(text="🔴 Stop", callback_data=f"stop_one:{sid}")
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text("✅ Started. Forwarding will run at your configured interval.\nOpen live status below.", reply_markup=kb.as_markup())
    except:
        await cq.message.answer("✅ Started. Forwarding will run at your configured interval.", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data.startswith("stop_one:"))
async def stop_one(cq: CallbackQuery):
    uid = cq.from_user.id
    sid = int(cq.data.split(":")[1])
    stop_campaign_for(uid, sid)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Live Status", url=f"https://t.me/{ENV.LOG_BOT_USERNAME}")
    kb.button(text="▶️ Start", callback_data=f"go_one:{sid}")
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text("🔴 Stopped for selected account.", reply_markup=kb.as_markup())
    except:
        await cq.message.answer("🔴 Stopped for selected account.", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data == "start_all")
async def start_all(cq: CallbackQuery):
    uid = cq.from_user.id
    started = 0
    for sid, *_ in list_sessions(uid):
        if (uid, sid) in RUNNING_TASKS and RUNNING_TASKS[(uid,sid)] and not RUNNING_TASKS[(uid,sid)].cancelled() and not RUNNING_TASKS[(uid,sid)].done(): 
            continue
        try:
            await start_campaign_for(cq.bot, None, _AUX["log_bot"], ENV.OWNER_ID, uid, sid, kb_welcome_gating())
            started += 1
        except Exception:
            continue
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Live Status", url=f"https://t.me/{ENV.LOG_BOT_USERNAME}")
    kb.button(text="🔴 Stop All", callback_data="ads_stop_all")
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text(f"Started {started} account(s).", reply_markup=kb.as_markup())
    except:
        await cq.message.answer(f"Started {started} account(s).", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data == "ads_stop_all")
async def stop_all(cq: CallbackQuery):
    uid = cq.from_user.id
    count = 0
    for (u,s), t in list(RUNNING_TASKS.items()):
        if u == uid and t and not t.cancelled():
            t.cancel()
            RUNNING_TASKS.pop((u,s), None)
            count += 1

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Live Status", url=f"https://t.me/{ENV.LOG_BOT_USERNAME}")
    kb.row(InlineKeyboardButton(text="🔙 Back", callback_data="back_ads"))
    try:
        await cq.message.edit_text(f"🔴 Stopped {count} running account(s).", reply_markup=kb.as_markup())
    except:
        await cq.message.answer(f"🔴 Stopped {count} running account(s).", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.message(F.text == "✏️Customize Name")
async def customize_entry(m: Message):
    uid = m.from_user.id
    if not premium_active(uid):
        price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🚀 Buy Premium", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
        kb.button(text="OK, got it", callback_data="prem_ok")
        return await m.answer(
            f"<b>Go Premium — {price} 🚀</b>\n"
            "Run multiple accounts and unlock power features.\n"
            "<b>What you get</b>\n"
            "👥 Multiple accounts (manage more brands)\n"
            "💎 Multiple post link (rotate through posts)\n"
            "⚡ Priority lane: faster sending + top-tier support\n"
            f"Limited offer — upgrade now and save {ENV.PREMIUM_DISCOUNT_TEXT}.",
            reply_markup=kb.as_markup()
        )
    sessions = list_sessions(uid)
    if not sessions: return await m.answer("No accounts to customize.")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for sid, phone, *_ in sessions:
        kb.row(InlineKeyboardButton(text=phone, callback_data=f"cust_pick:{sid}"))
    await m.answer("Customize account Name and Bio:\nChoose Account:", reply_markup=kb.as_markup())

CUSTOMIZE_STATE = {}

@rt_main.callback_query(F.data.startswith("cust_pick:"))
async def cust_pick(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid): return await cq.answer("Premium only.", show_alert=True)
    sid = int(cq.data.split(":")[1])
    CUSTOMIZE_STATE[uid] = {"sid": sid, "mode":None, "first":None, "last":None, "bio":None}
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="First name", callback_data="cust_first")
    kb.button(text="Last name", callback_data="cust_last")
    kb.button(text="Bio", callback_data="cust_bio")
    kb.row(InlineKeyboardButton(text="💾 Save", callback_data="cust_save"), InlineKeyboardButton(text="🔙 Main Menu", callback_data="back_main"))
    try: await cq.message.edit_text("Select what to edit:", reply_markup=kb.as_markup())
    except: await cq.message.answer("Select what to edit:", reply_markup=kb.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data == "cust_first")
async def cust_first(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid): return await cq.answer("Premium only.", show_alert=True)
    st = CUSTOMIZE_STATE.get(uid, {}); st["mode"] = "first"; CUSTOMIZE_STATE[uid] = st
    await cq.message.answer("Send new <b>First name</b> text."); await cq.answer()

@rt_main.callback_query(F.data == "cust_last")
async def cust_last(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid): return await cq.answer("Premium only.", show_alert=True)
    st = CUSTOMIZE_STATE.get(uid, {}); st["mode"] = "last"; CUSTOMIZE_STATE[uid] = st
    await cq.message.answer("Send new <b>Last name</b> text."); await cq.answer()

@rt_main.callback_query(F.data == "cust_bio")
async def cust_bio(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid): return await cq.answer("Premium only.", show_alert=True)
    st = CUSTOMIZE_STATE.get(uid, {}); st["mode"] = "bio"; CUSTOMIZE_STATE[uid] = st
    await cq.message.answer("Send new <b>Bio</b> text."); await cq.answer()

@rt_main.callback_query(F.data == "cust_save")
async def cust_save(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid): return await cq.answer("Premium only.", show_alert=True)
    st = CUSTOMIZE_STATE.get(uid)
    if not st: return await cq.answer()
    sid = st["sid"]; first = st.get("first"); last = st.get("last"); bio = st.get("bio")
    from ..core.repo import get_session_path
    session_path = get_session_path(sid)
    if not session_path: return await cq.message.answer("Session missing.")
    from telethon import functions
    from ..telethon.client import client_from_session_file
    client = await client_from_session_file(session_path)
    try:
        await client(functions.account.UpdateProfileRequest(first_name=first or None, last_name=last or None, about=bio or None))
        await cq.message.answer("Saved.")
    except Exception as e:
        await cq.message.answer(f"Failed to save: {e}")
    await client.disconnect(); CUSTOMIZE_STATE.pop(uid, None); await cq.answer()

@rt_main.callback_query(F.data == "back_main")
async def back_main(cq: CallbackQuery):
    try:
        await cq.message.edit_text("Main menu:", reply_markup=main_menu_kb())
    except:
        await cq.message.answer("Main menu:", reply_markup=main_menu_kb())
    await cq.answer()

@rt_main.message(F.text == "🛟Support")
async def support(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="🛟 24/7 Support — DM us", url="https://t.me/CamprunsAdminss_bot")
    await m.answer(
        "<b>🛟 24/7 Support — DM us</b>\n"
        "Got an issue? Need promotions? Want a custom bot or software?\n"
        "• 📣 Promotions & bulk campaigns\n"
        "• 🤖 Bot builds & integrations\n"
        "• 🛠️ Software customization & automation\n"
        "<b>Real humans. Fast replies. Confidential.</b>",
        reply_markup=kb.as_markup()
    )

@rt_main.message(F.text == "⭐ Subscriptions")
async def subs(m: Message):
    from ..core.repo import premium_until
    if premium_active(m.from_user.id):
        nm = (m.from_user.first_name or m.from_user.username or "Friend")
        await m.answer(
            f"<b>💛 Thank you, {nm}! Premium is active</b>\n"
            f"✅ You’re already on Premium.\n"
            f"🗓️ Active until : {format_local_dt(premium_until(m.from_user.id))}.\n",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Main Menu", callback_data="back_main")]])
        )

    else:
        price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder(); kb.button(text="⚡ Buy Now", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
        await m.answer(
            f"<b>Go Premium — {price} 🚀</b>\n"
            "\n"
            "<b>Unlock all features:</b>\n"
            "• 👥 <b>Multiple accounts</b> — add and manage more accounts\n"
            "• 💎 <b>Multiple post link</b> — rotate between different posts\n"
            "• ⚡️ <b>Priority high</b> — faster sending & support\n"
            "• 🕒 <b>Auto Mode</b> — run ads only in your chosen hours\n"
            "• 🧵 <b>Forum topics</b> — send in specific topics\n"
            "• ⏱️ <b>Per-group interval</b> — set time interval per group\n"
            "• 😎 <b>Premium emoji support</b> — use premium emoji without Telegram Premium\n"
            "\n"
            "<i>Buy now and unlock everything.</i>",
            reply_markup=kb.as_markup()
        )

@rt_main.message(F.text == "📨 Total Messages Sent")
async def total_sent(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    t1, _, total, env_total = user_totals_text(m.from_user.id)
    await m.answer(t1)

@rt_main.message(F.text == "📊 Ads Message Total Sent")
async def ads_total_sent(m: Message):
    if await _maybe_premium_mode_gate_msg(m):
        return
    _, _, total, env_total = user_totals_text(m.from_user.id)
    from ..features.milestones import status_for_user
    block = status_for_user(m.from_user.id, admin_view=False)
    text = (
        f"<b>📨 Ads Sent:</b> <b>{env_total}</b>\n\n"
        f"{block}\n\n"
        "<b>Need payout?</b>\n"
        "1) Reach a milestone (20k/35k/1L) using the exact ad text.\n"
        "2) Take a screenshot of your Ads Sent count.\n"
        "3) DM us at @CamprunsAdminss_bot with the screenshot and your UPI/Bank/Wallet details.\n"
        "We’ll verify and pay ASAP 🚀"
    )
    uid = m.from_user.id
    sessions = list_sessions(uid)
    running_any = any(((uid, sid) in RUNNING_TASKS and RUNNING_TASKS[(uid,sid)] and not RUNNING_TASKS[(uid,sid)].cancelled() and not RUNNING_TASKS[(uid,sid)].done()) for sid, *_ in sessions)
    await m.answer(text, reply_markup=public_ads_controls_kb(starting=running_any))

@rt_main.callback_query(F.data == "pubads_start")
async def pubads_start(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    if not sessions:
        login_username = ENV.LOGIN_BOT_USERNAME or "LoginBot"
        await cq.message.answer("Link an account first:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Open Login Bot", url=f"https://t.me/{login_username}?start=connect")]
        ]))
        return await cq.answer()
    sid = sessions[-1][0]
    from ..core.repo import get_session_path
    session_path = get_session_path(sid)
    if not session_path:
        await cq.answer("Session missing.", show_alert=True); return
    client = await client_from_session_file(session_path)
    try:
        post_link = await create_env_ad_post_and_link(client)
    finally:
        try: await client.disconnect()
        except Exception: pass

    insert_campaign(uid, sid, post_link, [post_link], 3*60, "all", [])
    await start_campaign_for(cq.bot, None, _AUX["log_bot"], ENV.OWNER_ID, uid, sid, kb_welcome_gating())
    await cq.message.edit_reply_markup(reply_markup=public_ads_controls_kb(starting=True))
    await cq.answer("Started")

@rt_main.callback_query(F.data == "pubads_stop")
async def pubads_stop(cq: CallbackQuery):
    uid = cq.from_user.id
    sessions = list_sessions(uid)
    count = 0
    for sid, *_ in sessions:
        if (uid, sid) in RUNNING_TASKS:
            stop_campaign_for(uid, sid)
            count += 1
    await cq.message.edit_reply_markup(reply_markup=public_ads_controls_kb(starting=False))
    await cq.answer(f"Stopped {count} task(s).")

@rt_main.callback_query(F.data == "pubads_auto")
async def pubads_auto(cq: CallbackQuery):
    uid = cq.from_user.id
    if not premium_active(uid):
        price = f"${int(ENV.PREMIUM_PRICE_USD)}/{ENV.PREMIUM_MONTHS_LABEL}"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🚀 Buy Premium", url=f"https://t.me/{ENV.BUY_PREMIUM_USERNAME}")
        kb.button(text="OK, got it", callback_data="prem_ok")
        await cq.message.answer(
            f"<b>Go Premium — {price} 🚀</b>\n"
            "\n"
            "<b>Unlock all features:</b>\n"
            "• 👥 <b>Multiple accounts</b> — add and manage more accounts\n"
            "• 💎 <b>Multiple post link</b> — rotate between different posts\n"
            "• ⚡️ <b>Priority high</b> — faster sending & support\n"
            "• 🕒 <b>Auto Mode</b> — run ads only in your chosen hours\n"
            "• 🧵 <b>Forum topics</b> — send in specific topics\n"
            "• ⏱️ <b>Per-group interval</b> — set time interval per group\n"
            "• 😎 <b>Premium emoji support</b> — use premium emoji without Telegram Premium\n"
            "\n"
            f"<i>Buy now and unlock everything.</i> Limited offer — upgrade now and save {ENV.PREMIUM_DISCOUNT_TEXT}.",
            reply_markup=kb.as_markup()
        )
        return await cq.answer()
    from ..core.repo import get_cfg, set_cfg
    cfg = get_cfg(f"auto_mode:{uid}", None)
    enabled = isinstance(cfg, dict) and cfg.get("enabled")
    if enabled:
        try:
            start_min = int(cfg.get("start", 0))
            end_min = int(cfg.get("end", 0))
            window_str = f"{_mins_to_12h(start_min)} - {_mins_to_12h(end_min)}"
        except Exception:
            window_str = "not set"
        status = (
            "🕒 Auto Mode is currently <b>ON</b>.\n"
            f"Current daily window: <b>{window_str}</b>\n\n"
        )
    else:
        status = (
            "🕒 Auto Mode is currently <b>OFF</b>.\n"
            "Your ads run all day according to your interval.\n\n"
        )
    text = (
        status +
        "Use the buttons below to turn Auto Mode ON or OFF.\n\n"
        "Tap <b>ON</b> to set a daily time window or <b>OFF</b> to disable Auto Mode."
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb2 = InlineKeyboardBuilder()
    kb2.button(text="🟢 Auto ON", callback_data="auto_on")
    kb2.button(text="🔴 Auto OFF", callback_data="auto_off")
    await cq.message.answer(text, reply_markup=kb2.as_markup())
    await cq.answer()

@rt_main.callback_query(F.data == "auto_on")
async def cb_auto_on(cq: CallbackQuery):
    uid = cq.from_user.id
    AUTO_MODE_EXPECTING.add(uid)
    await cq.message.answer(
        "Send the daily time window in this format:\n"
        "<code>3:30 am - 2:00 pm</code>\n\n"
        "Or send <b>off</b> to disable Auto Mode and run ads full-time."
    )
    await cq.answer()


@rt_main.callback_query(F.data == "auto_off")
async def cb_auto_off(cq: CallbackQuery):
    uid = cq.from_user.id
    from ..core.repo import set_cfg
    set_cfg(f"auto_mode:{uid}", {"enabled": False})
    AUTO_MODE_EXPECTING.discard(uid)
    await cq.message.answer(
        "🕒 Auto Mode is now <b>OFF</b>.\n"
        "Your ads will run all day according to your interval."
    )
    await cq.answer()

@rt_main.callback_query(F.data == "back_ads")
async def back_ads(cq: CallbackQuery):
    from .keyboards import kb_ads_manager_menu
    try:
        await cq.message.edit_text("Ads manager:", reply_markup=kb_ads_manager_menu())
    except Exception:
        await cq.message.answer("Ads manager:", reply_markup=kb_ads_manager_menu())
    await cq.answer()

@rt_main.message(CommandStart())
async def main_start_deeplink(m: Message):
    payload = ""
    try:
        parts = (m.text or "").split(" ", 1)
        payload = parts[1].strip() if len(parts) > 1 else ""
    except Exception:
        payload = ""

    if payload.lower() in {"ads", "ads_setup", "start_ads"}:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🛠️ Setup Campaigns", callback_data="ads_setup")
        try:
            await m.answer("🚀 Ready — open Ads Manager:", reply_markup=kb.as_markup())
        except Exception:
            await m.answer("🚀 Ready — open Ads Manager:")
        return

    try:
        await m.answer("Main menu:", reply_markup=main_menu_kb())
    except Exception:
        await m.answer("Main menu:")


@rt_main.callback_query(F.data.startswith("tag_mode:"))
async def set_tag_mode(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid) or {}
    choice = cq.data.split(":",1)[1]
    from ..core.repo import premium_active, set_cfg
    if choice == "with":
        if not premium_active(uid):
            await cq.answer("Premium only feature. Upgrade to use 'With tag'.", show_alert=True)
            return
        st["with_tag"] = True
        set_cfg(f"campaign_tag_mode:{uid}", "with")
    else:
        st["with_tag"] = False
        set_cfg(f"campaign_tag_mode:{uid}", "hide")
    st["step"] = "ask_topics"
    SETUP_STATE[uid] = st
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭️ Skip topics", callback_data="topics_skip")
    try: await cq.message.delete()
    except: pass
    await cq.message.answer(
        "Send the list of Topic links (one per line). Or tap Skip.",
        reply_markup=kb.as_markup()
    )
    await cq.answer()

@rt_main.callback_query(F.data == "topics_skip")
async def topics_skip(cq: CallbackQuery):
    uid = cq.from_user.id
    st = SETUP_STATE.get(uid) or {}
    from ..core.repo import set_cfg, premium_active
    st["topic_links"] = []
    set_cfg(f"campaign_topic_links:{uid}", [])
    if premium_active(uid):
        st["step"] = "ask_target_delay"
        SETUP_STATE[uid] = st
        try: await cq.message.delete()
        except: pass
        await cq.message.answer(
            "Premium feature:\nSend delay range between each group/topic in seconds.\nExample: 5-10",
        )
        await cq.answer()
        return
    st["step"] = "ask_interval"
    SETUP_STATE[uid] = st
    try: await cq.message.delete()
    except: pass
    await cq.message.answer("Now set the interval:", reply_markup=kb_setup_intervals())
    await cq.answer()

@rt_main.message(F.text.regexp(TIME_RANGE_RE))
async def auto_mode_set_window(m: Message):
    uid = m.from_user.id
    if uid not in AUTO_MODE_EXPECTING:
        return
    rng = _parse_time_range_to_minutes(m.text or "")
    if not rng:
        await m.answer(
            "Could not understand that time range.\n"
            "Please use format like <code>3:30 am - 2:00 pm</code>."
        )
        return
    start_min, end_min = rng
    from ..core.repo import set_cfg
    set_cfg(f"auto_mode:{uid}", {"enabled": True, "start": start_min, "end": end_min})
    AUTO_MODE_EXPECTING.discard(uid)
    if end_min > start_min:
        mins = end_min - start_min
    else:
        mins = (24 * 60 - start_min) + end_min
    hours = mins // 60
    rem = mins % 60
    if hours > 0:
        dur = f"{hours} hour {rem} minutes" if hours == 1 else f"{hours} hours {rem} minutes"
    else:
        dur = f"{rem} minutes"
    window_str = f"{_mins_to_12h(start_min)} - {_mins_to_12h(end_min)}"
    await m.answer(
        "🕒 Auto Mode is now <b>ON</b>.\n"
        f"Daily run window: <b>{window_str}</b>\n"
        f"Approx. run time per day: <b>{dur}</b>."
    )


@rt_main.message(F.text.regexp(re.compile(r"(?i)^\s*off\s*$")))
async def auto_mode_turn_off(m: Message):
    uid = m.from_user.id
    if uid not in AUTO_MODE_EXPECTING:
        return
    from ..core.repo import set_cfg
    set_cfg(f"auto_mode:{uid}", {"enabled": False})
    AUTO_MODE_EXPECTING.discard(uid)
    await m.answer(
        "🕒 Auto Mode is now <b>OFF</b>.\n"
        "Your ads will run all day according to your interval."
    )

@rt_main.message(F.text)
async def handle_topics_step(m: Message):
    uid = m.from_user.id
    st = SETUP_STATE.get(uid)
    if not st:
        return
    step = st.get("step")
    # step 1: collect topic links
    if step == "ask_topics":
        from ..features.campaign_topics import extract_topic_links
        from ..core.repo import set_cfg, premium_active
        links = extract_topic_links(m.text or "")
        st["topic_links"] = links
        set_cfg(f"campaign_topic_links:{uid}", links)
        # if premium, next step is target-delay; else go to batch interval
        if premium_active(uid):
            st["step"] = "ask_target_delay"
            SETUP_STATE[uid] = st
            await m.answer(
                "Premium feature:\nSend delay range between each group/topic in seconds.\nExample: 5-10",
            )
            return
        st["step"] = "ask_interval"
        SETUP_STATE[uid] = st
        await m.answer(f"✅ Saved {len(links)} topic link(s).\nNow set the interval:", reply_markup=kb_setup_intervals())
        return
    # step 2: premium per-target delay
    if step == "ask_target_delay":
        from ..core.repo import set_cfg
        txt = (m.text or "").strip()
        import re as _re
        m_rng = _re.match(r"^(\d+)\s*[-–]\s*(\d+)$", txt)
        if m_rng:
            lo = int(m_rng.group(1))
            hi = int(m_rng.group(2))
        else:
            if txt.isdigit():
                lo = hi = int(txt)
            else:
                await m.answer("Please send like 5-10 (min-max seconds).")
                return
        # validate range for premium: 5-90 seconds
        if lo < 5 or hi > 90 or lo > hi:
            await m.answer("Range must be between 5 and 90 seconds, e.g. 5-10.")
            return
        st["target_delay"] = [lo, hi]
        set_cfg(f"campaign_target_delay:{uid}", [lo, hi])
        st["step"] = "ask_interval"
        SETUP_STATE[uid] = st
        await m.answer(
            f"✅ Saved per-target delay: {lo}-{hi} seconds.\nNow set the campaign interval:",
            reply_markup=kb_setup_intervals(),
        )



    # step 3: premium custom campaign interval
    if step == "ask_custom_interval":
        txt_val = (m.text or "").strip().lower()
        import re as _re
        sec = None
        m_min = _re.match(r"^(\d+)\s*(m|min|mins|minute|minutes)$", txt_val)
        m_sec = _re.match(r"^(\d+)\s*(s|sec|secs|second|seconds)$", txt_val)
        if m_min:
            sec = int(m_min.group(1)) * 60
        elif m_sec:
            sec = int(m_sec.group(1))
        elif txt_val.isdigit():
            # plain number = minutes
            sec = int(txt_val) * 60
        else:
            await m.answer(
                "Please send the interval in seconds or minutes, like\n"
                "<code>45s</code>, <code>45 sec</code>, <code>2m</code>, or <code>2 min</code>."
            )
            return
        # limit from 5 seconds up to 7 days
        if sec < 5 or sec > 60*60*24*7:
            await m.answer("Interval must be between 5 seconds and 7 days.")
            return
        st["interval"] = sec
        st["step"] = "group_choice"
        SETUP_STATE[uid] = st
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ All groups", callback_data="grp_all")
        kb.button(text="🎯 Choose groups", callback_data="grp_choose")
        await m.answer(
            "📣 Select Group\nChoose where to send your campaign.",
            reply_markup=kb.as_markup(),
        )
        return
