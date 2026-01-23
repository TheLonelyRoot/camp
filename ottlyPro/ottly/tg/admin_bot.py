from functools import wraps
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from ..core.config import ENV
from ..core.db import db
from .keyboards import admin_main_kb, admin_access_kb, ban_manage_kb, stats_quick_actions_kb
from ..features.metrics import global_totals
from ..core.timeutil import format_local_dt, format_duration
from ..features.milestones import parse_admin_payline, milestone_met, payment_confirmation_text, status_for_user, reset_after_payment
from ..core.repo import (
    get_user_field, add_payment, list_transactions, remove_premium, set_cfg, get_cfg,
    add_admin, remove_admin, user_by_username, set_ban, unban, set_premium_months, premium_until
)
from .middleware import set_downtime, downtime_active, downtime_reason, downtime_started_utc
from ..features.campaigns import RUNNING_TASKS

rt_admin = Router()
ADMIN_BROADCAST_MODE = {}

def owner_only(func):
    @wraps(func)
    async def wrapper(m: Message, *args, **kwargs):
        return await func(m)
        return await func(m)
    return wrapper

def clear_admin_states():
    for k in [
        "await_admin_add","await_admin_rm",
        "await_ban_add","await_ban_rm",
        "await_add_pro","await_remove_sub_userid","await_remove_sub_reason_uid",
        "await_dt_reason","await_dt_start_reason","await_dt_stop_note",
        "await_broadcast_text"
    ]:
        set_cfg(k, False)
    ADMIN_BROADCAST_MODE.clear()

async def broadcast_all_main(text: str) -> tuple[int,int]:
    main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    con = db(); cur = con.cursor()
    cur.execute("SELECT user_id FROM users")
    ids = [r[0] for r in cur.fetchall()]
    con.close()
    sent = 0; fail = 0
    for uid in ids:
        try:
            await main_bot.send_message(uid, text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            fail += 1
    return sent, fail

@rt_admin.message(CommandStart())
async def admin_start(m: Message):
    # Owner check removed
    clear_admin_states()
    await m.answer("Welcome, Owner.", reply_markup=admin_main_kb())

@rt_admin.message(F.text == "📊 Stats")
@owner_only
async def admin_stats(m: Message):
    clear_admin_states()
    con = db(); cur = con.cursor()
    total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    sessions_saved = cur.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    active_api_creds = cur.execute("SELECT COUNT(*) FROM sessions WHERE is_active=1").fetchone()[0]
    campaigns_total = cur.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    active_users = cur.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE is_active=1").fetchone()[0]
    con.close()

    ads_running = sum(1 for t in RUNNING_TASKS.values() if t and not t.cancelled() and not t.done())
    inactive_users = max(0, total_users - active_users)
    sys_online = "Online" if not downtime_active() else "Offline"

    g_total, g_ads = global_totals()

    await m.answer("Admin stats unavailable (credentials removed)")

@rt_admin.callback_query(F.data == "stats_manage_user")
async def stats_manage_user(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    await cq.message.answer("Select an action:", reply_markup=admin_access_kb())
    await cq.answer()

@rt_admin.callback_query(F.data == "stats_ban_mgmt")
async def stats_ban_mgmt(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    await cq.message.answer("Choose:", reply_markup=ban_manage_kb())
    await cq.answer()

@rt_admin.message(F.text == "1) acess of bot")
@owner_only
async def access_of_bot(m: Message):
    clear_admin_states()
    await m.answer("Select an action:", reply_markup=admin_access_kb())

@rt_admin.callback_query(F.data == "admin_add")
async def cb_admin_add(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_admin_add", True)
    await cq.message.answer("Add admin in format: <code>user_id | username</code>")
    await cq.answer()

@rt_admin.callback_query(F.data == "admin_rm")
async def cb_admin_rm(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_admin_rm", True)
    await cq.message.answer("Remove admin in format: <code>user_id | username</code>")
    await cq.answer()

@rt_admin.callback_query(F.data == "admin_list")
async def cb_admin_list(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    con = db(); cur = con.cursor()
    cur.execute("SELECT user_id, username FROM admins ORDER BY user_id")
    rows = cur.fetchall()
    con.close()
    if not rows: await cq.message.answer("No admins yet.")
    else:
        lines = [f"• {uid} @{uname}" for uid,uname in rows]
        await cq.message.answer("<b>Admins</b>\n" + "\n".join(lines))
    await cq.answer()

@rt_admin.message(F.text == "2) Ban Members")
@owner_only
async def ban_members(m: Message):
    clear_admin_states()
    await m.answer("Choose:", reply_markup=ban_manage_kb())

@rt_admin.callback_query(F.data == "ban_add")
async def cb_ban_add(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_ban_add", True)
    await cq.message.answer(
        "Send in format:\n<code>username or userid | Permanent or Temporary | duration (days or —)</code>\n"
        "Examples:\n<code>@john | Permanent | —</code>\n<code>123456 | Temporary | 7</code>"
    ); await cq.answer()

@rt_admin.callback_query(F.data == "ban_rm")
async def cb_ban_rm(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_ban_rm", True)
    await cq.message.answer("Send username or user_id to unban."); await cq.answer()

@rt_admin.callback_query(F.data == "ban_list")
async def cb_ban_list(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    con = db(); cur = con.cursor()
    cur.execute("SELECT user_id, reason, ban_type, until_utc FROM bans")
    rows = cur.fetchall(); con.close()
    if not rows: await cq.message.answer("No banned users.")
    else:
        lines = []
        for uid,reason,btype,until in rows:
            until_local = format_local_dt(until) if until else "—"
            lines.append(f"• {uid} — {btype or 'Permanent'} — until {until_local} — reason: {reason or '—'}")
        await cq.message.answer("<b>Banned Users</b>\n" + "\n".join(lines))
    await cq.answer()

@rt_admin.message(F.text == "3) Add members for pro")
@owner_only
async def add_members_for_pro(m: Message):
    clear_admin_states()
    set_cfg("await_add_pro", True)
    await m.answer("Send in format: <code>user_id | months | Price</code>\nExample: <code>123456789 | 3 | 15</code>")

@rt_admin.message(F.text == "4) 📋 Active Subscriptions")
@owner_only
async def active_subs(m: Message):
    clear_admin_states()
    con = db(); cur = con.cursor()
    cur.execute("""SELECT user_id, username, plan_label, premium_until
                   FROM users
                   WHERE is_premium=1 AND (premium_until IS NULL OR premium_until>?)
                   ORDER BY COALESCE(premium_until, '9999-12-31T23:59:59') ASC""", (datetime.utcnow().isoformat(),))
    rows = cur.fetchall(); con.close()
    if not rows:
        await m.answer("No active subscriptions."); 
    else:
        lines = []
        for idx,(uid,uname,plan,until_iso) in enumerate(rows, start=1):
            until_local = format_local_dt(until_iso) if until_iso else "Lifetime"
            plan_emoji = "💎"
            handle = f"@{uname}" if uname else "(no username)"
            lines.append(
                f"{idx}️⃣ 👤 User: {handle}\n"
                f"🆔 User ID: {uid}\n"
                f"{plan_emoji} Plan: {plan or 'Premium'} — Active until {until_local}\n"
            )
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="📤 Export List", callback_data="subs_export"),
            InlineKeyboardButton(text="🔄 Refresh", callback_data="subs_refresh")
        )
        kb.row(
            InlineKeyboardButton(text="📋 Expired Subs", callback_data="expired_subs"),
            InlineKeyboardButton(text="📣 Nudge Expired", callback_data="expired_broadcast")
        )
        kb.row(InlineKeyboardButton(text="❌ Close", callback_data="subs_close"))
        await m.answer("\n".join(lines).strip(), reply_markup=kb.as_markup())

@rt_admin.message(F.text == "5) Total Transcations")
@owner_only
async def total_transactions(m: Message):
    clear_admin_states()
    rows = list_transactions(100)
    if not rows:
        return await m.answer("No transactions yet.")
    lines = ["<b>Recent Transactions</b>"]
    for tid, uid, amt, curr, plan, at in rows:
        lines.append(f"#{tid} — uid {uid} — {curr} {amt} — {plan or 'Premium'} — {format_local_dt(at) if at else '—'}")
    await m.answer("\n".join(lines))

@rt_admin.message(F.text == "6) Downtime")
@owner_only
async def downtime_menu(m: Message):
    clear_admin_states()
    on = downtime_active()
    state = "ON 🔴" if on else "OFF 🟢"
    from ..core.repo import get_cfg
    prem_on = bool(get_cfg("premium_mode:on", False))
    prem_state = "Premium Mode: ON 💰" if prem_on else "Premium Mode: OFF 💸"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Start Downtime", callback_data="dt_start")],
        [InlineKeyboardButton(text="Stop Downtime", callback_data="dt_stop")],
        [InlineKeyboardButton(text="Set Reason Only", callback_data="dt_reason")],
        [InlineKeyboardButton(text=prem_state, callback_data="prem_toggle")],
    ])
    await m.answer(f"Downtime is currently: <b>{state}</b>\nReason: {downtime_reason()}", reply_markup=kb)


@rt_admin.callback_query(F.data == "prem_toggle")
async def prem_toggle(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: 
        return await cq.answer("Owner only.")
    from ..core.repo import get_cfg, set_cfg
    curr = bool(get_cfg("premium_mode:on", False))
    set_cfg("premium_mode:on", not curr)
    # refresh menu
    return await downtime_menu(cq.message)

@rt_admin.callback_query(F.data == "dt_start")
async def dt_start(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_dt_start_reason", True)
    await cq.message.answer("Send downtime <b>reason</b> to start:")
    await cq.answer()

@rt_admin.callback_query(F.data == "dt_stop")
async def dt_stop(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_dt_stop_note", True)
    await cq.message.answer("Send <b>note</b> for uptime announcement:")
    await cq.answer()

@rt_admin.callback_query(F.data == "dt_reason")
async def dt_reason(cq: CallbackQuery):
    if cq.from_user.id != ENV.OWNER_ID: return await cq.answer("Owner only.")
    clear_admin_states()
    set_cfg("await_dt_reason", True)
    await cq.message.answer("Send new downtime reason text:")
    await cq.answer()

@rt_admin.message(F.text == "7) Remove Subscription")
@owner_only
async def remove_subscription_prompt(m: Message):
    clear_admin_states()
    set_cfg("await_remove_sub_userid", True)
    await m.answer("Send user_id to remove premium from:")

@rt_admin.message(F.text == "📣 Broadcast")
@owner_only
async def broadcast_prompt(m: Message):
    clear_admin_states()
    set_cfg("await_broadcast_text", True)
    await m.answer("Send the broadcast message (HTML supported). It will be sent to all users on the <b>main bot</b>.")

@rt_admin.message(F.text == "💸 Give Payment to User")
@owner_only
async def pay_user_prompt(m: Message):
    clear_admin_states()
    await m.answer("Send in format: <code>Userid | 20k(message) | ₹10 | [UPI/Bank/Wallet] | [TXNID]</code>")

@rt_admin.message(F.text == "🔎 Users Milestone Check")
@owner_only
async def milestone_check_prompt(m: Message):
    clear_admin_states()
    await m.answer("Send <code>UserId</code> to view milestone status & total paid.")

@rt_admin.message()
@owner_only
async def admin_free_text(m: Message):
    txt = (m.text or "").strip()

    if get_cfg("await_admin_add", False):
        set_cfg("await_admin_add", False)
        try:
            uid_s, uname = [p.strip() for p in txt.split("|", 1)]
            uid = int(uid_s)
            add_admin(uid, uname.lstrip("@"))
            return await m.answer(f"✅ Added admin: {uid} @{uname.lstrip('@')}")
        except Exception as e:
            return await m.answer(f"❌ Failed to add admin: {e}")

    if get_cfg("await_admin_rm", False):
        set_cfg("await_admin_rm", False)
        try:
            uid_s, _ = [p.strip() for p in txt.split("|", 1)]
            uid = int(uid_s)
            remove_admin(uid)
            return await m.answer(f"✅ Removed admin: {uid}")
        except Exception as e:
            return await m.answer(f"❌ Failed to remove admin: {e}")

    if get_cfg("await_ban_add", False):
        set_cfg("await_ban_add", False)
        try:
            left, btype, dur = [p.strip() for p in txt.split("|")]
            if left.startswith("@"):
                row = user_by_username(left)
                if not row: return await m.answer("User not found by username.")
                uid = row[0]
            else:
                uid = int(left)
            until_iso = None
            reason = "Admin action"
            btype = btype.capitalize()
            if btype.startswith("Temp"):
                days_digits = "".join(ch for ch in dur if ch.isdigit())
                days = int(days_digits or "0")
                until_iso = (datetime.utcnow() + timedelta(days=days)).isoformat()
            set_ban(uid, reason, btype, until_iso)
            try:
                main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                ban_date = format_local_dt(datetime.utcnow().isoformat())
                await main_bot.send_message(
                    uid,
                    "<b>⚠️ Access Restricted</b>\n\n"
                    "You’ve been <b>banned</b> by the admin.\n"
                    f"🗓️ <b>Date:</b> {ban_date}\n"
                    f"❗ <b>Reason:</b> {reason}\n\n"
                    f"📩 Need help? Contact <b>@{ENV.ASSIST_USERNAME}</b>"
                )
            except Exception:
                pass
            return await m.answer(f"🚫 Banned {uid} — {btype} {(f'until {format_local_dt(until_iso)}' if until_iso else '')}")
        except Exception as e:
            return await m.answer(f"❌ Failed to ban: {e}")

    if get_cfg("await_ban_rm", False):
        set_cfg("await_ban_rm", False)
        try:
            if txt.startswith("@"):
                row = user_by_username(txt)
                if not row: return await m.answer("User not found by username.")
                uid = row[0]
            else:
                uid = int(txt)
            unban(uid)
            return await m.answer(f"✅ Unbanned {uid}")
        except Exception as e:
            return await m.answer(f"❌ Failed to unban: {e}")

    if get_cfg("await_add_pro", False):
        set_cfg("await_add_pro", False)
        try:
            uid_s, months_s, price_s = [p.strip() for p in txt.split("|")]
            uid = int(uid_s); months = int(months_s); price = float(price_s)
            set_premium_months(uid, months, price)
            valid_till = format_local_dt(premium_until(uid))
            fname = get_user_field(uid, "first_name", "there") or "there"
            price_str = int(price)
            receipt = (
                f"<b>🎉 Thanks for buying Premium, {fname}!</b>\n"
                f"You're now a <b>CAMP RUN Premium</b> member.\n\n"
                f"<b>Access:</b> All features unlocked\n"
                f"• 👥 Multiple accounts\n"
                f"• 💎 Multiple post link (rotate through posts)\n\n"
                f"• 📊 CAMP RUN campaign stats & logs\n"
                f"• 🛟 Priority Support — @CamprunsAdminss_bot\n\n"
                f"<b>Plan:</b> ${price_str}/month\n"
                f"<b>Valid till:</b> <b>{valid_till}</b>"
            )
            try:
                main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                await main_bot.send_message(uid, receipt)
            except Exception:
                pass
            return await m.answer(f"✅ Set Premium for {uid} — {months} months.")
        except Exception as e:
            return await m.answer(f"❌ Failed to set premium: {e}")

    if get_cfg("await_remove_sub_userid", False):
        if txt.isdigit():
            set_cfg("await_remove_sub_userid", False)
            set_cfg("await_remove_sub_reason_uid", int(txt))
            return await m.answer("Send a short reason for removal:")
        else:
            return await m.answer("Please send a numeric user_id.")

    uid_for_remove = get_cfg("await_remove_sub_reason_uid", False)
    if uid_for_remove:
        set_cfg("await_remove_sub_reason_uid", False)
        try:
            uid = int(uid_for_remove)
            reason = txt
            remove_premium(uid)
            name = get_user_field(uid, "first_name", "there") or "there"
            bot_name = ENV.BOT_DISPLAY_NAME or "CAMP RUN bot"
            plan = "Premium"
            dt = format_local_dt(datetime.utcnow().isoformat())
            msg = (
                f"⚠️ <b>Removal Notice, {name}!</b>\n"
                f"Your {bot_name} Premium is now cancelled.\n"
                f"Reason: {reason}\n"
                f"Access: Locked\n"
                "• 👥 Multiple accounts — disabled\n"
                "• 💎 Multiple post link — paused\n"
                "• 📊 CAMP RUN campaign stats & logs — hidden\n"
                "• 🛟 Priority Support — ended @CamprunsAdminss_bot\n\n"
                f"Plan: {plan} — Cancelled\n"
                f"Removed on: {dt}"
            )
            try:
                main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                await main_bot.send_message(uid, msg)
            except Exception:
                pass
            return await m.answer(f"Removed premium from user {uid}.")
        except Exception as e:
            return await m.answer(f"Failed to remove: {e}")

    if get_cfg("await_dt_reason", False):
        set_cfg("await_dt_reason", False)
        set_downtime(downtime_active(), txt)
        return await downtime_menu(await m.answer("✅ Reason updated."))

    if get_cfg("await_dt_start_reason", False):
        set_cfg("await_dt_start_reason", False)
        set_downtime(True, txt)
        started_iso = downtime_started_utc()
        started_local = format_local_dt(started_iso)
        duration = format_duration(started_iso)
        msg = ("🕒 Status: 🔴 Offline\n"
               f"📅 Downtime Started: {started_local}\n"
               f"⏳ Duration: {duration}\n"
               f"📌 Reason: {txt}")
        sent, fail = await broadcast_all_main(msg)
        return await m.answer(f"🔴 Downtime started and broadcast to {sent} users (failed {fail}).")

    if get_cfg("await_dt_stop_note", False):
        set_cfg("await_dt_stop_note", False)
        start_iso = downtime_started_utc()
        started_local = format_local_dt(start_iso) if start_iso else "Unknown"
        duration = format_duration(start_iso) if start_iso else "—"
        note = txt
        set_downtime(False, note)
        msg = (
            "✅ Thanks for your patience — the bot is now available 24/7.\n"
            "🕒 Status: 🟢 Online\n"
            f"📅 Uptime Started: {started_local}\n"
            f"⏳ Uptime: {duration}\n"
            f"🧰 Note: {note}"
        )
        sent, fail = await broadcast_all_main(msg)
        return await m.answer(f"🟢 Downtime stopped and broadcast to {sent} users (failed {fail}).")

    if get_cfg("await_broadcast_text", False):
        set_cfg("await_broadcast_text", False)
        sent, fail = await broadcast_all_main(txt)
        return await m.answer(f"📣 Broadcast sent to {sent} users (failed {fail}).")

    parsed = parse_admin_payline(txt)
    if parsed:
        uid, label, amount, mode, txn = parsed
        if not milestone_met(uid, label):
            return await m.answer("❌ Milestone not reached by this user yet.")
        add_payment(uid, amount, label, mode, txn)
        name = get_user_field(uid, "first_name", "User") or "User"
        confirmation = payment_confirmation_text(name, label, amount, mode, txn)
        try:
            main_bot = Bot(ENV.MAIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await main_bot.send_message(uid, confirmation)
        except Exception:
            pass
        reset_after_payment(uid)
        panel = status_for_user(uid, admin_view=True)
        return await m.answer(f"✅ Payment logged, user notified & milestones reset.\n\n{panel}")

    if txt.isdigit():
        uid = int(txt)
        panel = status_for_user(uid, admin_view=True)
        return await m.answer(panel)
