import asyncio
import json
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from telethon import functions
from ..core.repo import (
    list_sessions, insert_campaign, get_latest_campaign, get_latest_campaign_any, get_session_path,
    set_campaign_running, get_cfg, premium_active
)
from ..telethon.client import client_from_session_file
from ..telethon.forwards import forward_to_groups, parse_post_link
from ..features.pagination import slice_page
from ..tg.logging_svc import send_live_log
from ..core.timeutil import now_local

RUNNING_TASKS: dict[tuple[int,int], asyncio.Task] = {}

def _auto_mode_config(user_id: int):
    try:
        cfg = get_cfg(f"auto_mode:{user_id}", None)
    except Exception:
        cfg = None
    if not isinstance(cfg, dict):
        return None
    if not cfg.get("enabled"):
        return None
    try:
        start = int(cfg.get("start", 0))
        end = int(cfg.get("end", 24 * 60))
    except Exception:
        return None
    start = max(0, min(24 * 60, start))
    end = max(0, min(24 * 60, end))
    return start, end


def _auto_mode_allows_now(user_id: int) -> bool:
    cfg = _auto_mode_config(user_id)
    if not cfg:
        return True
    start, end = cfg
    now = now_local()
    mins = now.hour * 60 + now.minute
    if start == end:
        return False
    if start < end:
        return start <= mins < end
    return mins >= start or mins < end


async def _auto_mode_sleep(user_id: int, interval: int):
    cfg = _auto_mode_config(user_id)
    if not cfg:
        await asyncio.sleep(interval)
        return
    start, end = cfg
    now = now_local()
    mins = now.hour * 60 + now.minute
    if start == end:
        # misconfigured: don't send, just back off a bit
        await asyncio.sleep(60)
        return
    if start < end:
        if start <= mins < end:
            await asyncio.sleep(interval)
            return
        if mins < start:
            delta = start - mins
        else:
            delta = 24 * 60 - mins + start
    else:
        # window crosses midnight
        if mins >= start or mins < end:
            await asyncio.sleep(interval)
            return
        if mins < start:
            delta = start - mins
        else:
            delta = 24 * 60 - mins + start
    await asyncio.sleep(delta * 60)


# --- Lightweight cache to speed up group selection ---
DIALOGS_CACHE = {}  # session_path -> (ts, entries)
CACHE_TTL = 600  # 10 minutes

async def _list_group_dialogs_fast(client):
    entries = []
    async for d in client.iter_dialogs():
        ent = d.entity
        try:
            title = getattr(ent, "title", None) or getattr(ent, "username", None) or str(ent.id)
        except Exception:
            title = "Unknown"
        if getattr(ent, "megagroup", False) or getattr(d, "is_group", False):
            gid = getattr(ent, "id", None) or getattr(d, "id", None)
            if gid is None:
                continue
            entries.append((gid, title))
    entries.sort(key=lambda x: x[1].lower())
    return entries


async def count_all_groups_in_session(session_path:str) -> int:
    client = await client_from_session_file(session_path)
    try:
        await client.connect()
    except Exception:
        pass
    total = 0
    try:
        async for d in client.iter_dialogs():
            ent = d.entity
            if getattr(ent, "megagroup", False) or getattr(d, "is_group", False):
                total += 1
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return total

async def build_groups_markup(session_path:str, selected:set[int], page:int=0):
    # Build a fast, paginated list of groups using cached dialogs (gid, title)
    client = await client_from_session_file(session_path)
    try:
        await client.connect()
    except Exception:
        pass
    try:
        now_ts = int(__import__('time').time())
        cached = DIALOGS_CACHE.get(session_path)
        if cached and (now_ts - cached[0] < CACHE_TTL):
            entries = cached[1]
        else:
            entries = await _list_group_dialogs_fast(client)  # list[(gid, title)]
            DIALOGS_CACHE[session_path] = (now_ts, entries)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    # Paginate small pages for speed
    items, prev_page, next_page, total, pages = slice_page(entries, page, per_page=8)

    btn = InlineKeyboardBuilder()
    for gid, name in items:
        mark = "✅" if gid in selected else "➕"
        btn.row(InlineKeyboardButton(text=f"{mark} {name}", callback_data=f"pickgrp:{gid}"))

    btn.row(
        InlineKeyboardButton(text=f"✅ Save ({len(selected)})", callback_data=f"savegrps"),
        InlineKeyboardButton(text="Ads Manager Section", callback_data="back_ads")
    )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⏮️ Back", callback_data=f"grp_page:{prev_page}"))
    if (page+1) < pages:
        nav.append(InlineKeyboardButton(text="⏭️ Next", callback_data=f"grp_page:{next_page}"))
    if nav:
        btn.row(*nav)

    text = f"Tap to select groups. Page {page+1}/{max(1,pages)} (Total groups: {total})"
    return text, btn.as_markup()


async def ensure_campaign_channel(client):
    ch = None
    async for d in client.iter_dialogs():
        if d.is_channel and d.name.strip() == "🚀Here Send Campaign":
            ch = d.entity; break
    if not ch:
        res = await client(functions.channels.CreateChannelRequest(
            title="🚀Here Send Campaign",
            about="Auto-created by Ottly.",
            megagroup=False, for_import=False
        ))
        ch = res.chats[0]
        try:
            await client(functions.channels.UpdateUsernameRequest(ch, f"SetupOttlyAds{(await client.get_me()).id}"))
        except Exception:
            pass
    return ch

async def create_env_ad_post_and_link(client) -> str:
    from ..core.config import ENV
    link = ""
    ch = await ensure_campaign_channel(client)
    msg = await client.send_message(ch, ENV.ENV_AD_MESSAGE)
    username = getattr(ch, "username", None)
    if username:
        link = f"https://t.me/{username}/{msg.id}"
    else:
        cid = str(ch.id)
        if cid.startswith("-100"): cid = cid[4:]
        else: cid = cid.lstrip("-")
        link = f"https://t.me/c/{cid}/{msg.id}"
    return link

async def start_campaign_for(main_bot, admin_log_bot_unused, log_bot, owner_id: int, user_id:int, session_id:int, kb_join):
    latest = get_latest_campaign(user_id, session_id)
    if not latest:
        try:
            latest = get_latest_campaign_any(user_id)
        except Exception:
            latest = None
    if not latest:
        return
    camp_id, link, links_json, interval, mode, sel_json, is_running = latest
    try:
        links = json.loads(links_json) if links_json else []
    except Exception:
        links = []
    if not links:
        if link:
            links = [link]
        else:
            return

    session_path = get_session_path(session_id)
    # Stop previous running task for this session
    previous_task = RUNNING_TASKS.pop((user_id, session_id), None)
    if previous_task and not previous_task.cancelled():
        previous_task.cancel()
    if not session_path:
        return

    client = await client_from_session_file(session_path)
    try:
        await client.connect()
    except Exception:
        pass

    gids = []
    try:
        selected = json.loads(sel_json) if sel_json else []
        async for d in client.iter_dialogs():
            ent = d.entity
            if getattr(ent, "megagroup", False) or d.is_group:
                if mode == "all" or (mode == "choose" and selected and ent.id in selected):
                    gids.append(ent.id)
    except Exception:
        pass

    if not gids:
        await client.disconnect()
        return

    async def worker():
        try:
            set_campaign_running(camp_id, 1)

            # --- SEND THE ONE-TIME "started the campaign" LOG ---
            try:
                ts_str = now_local().strftime("%d/%m/%Y %H:%M:%S %Z")
                mins = int(interval // 60)
                first_link = links[0]
                init_text = (
                    "started the campaign \n"
                    f"🕒 {ts_str}\n"
                    f'🔗 Source: <a href="{first_link}">Open Post</a> \n'
                    f"👥 Total Group: {len(gids)}\n\n"
                    f"⏱ Interval: {int(interval)}s ({mins}m)"
                )
                await send_live_log(log_bot, user_id, init_text)
            except Exception:
                pass
            # ----------------------------------------------------

            first_peer, first_id = parse_post_link(links[0])
            if not first_peer or not first_id:
                set_campaign_running(camp_id, 0)
                return
            src = await client.get_input_entity(int(first_peer) if str(first_peer).lstrip("-").isdigit() else first_peer)

            # --- Premium forwarding mode & topic targets (from setup) ---
            try:
                tag_mode = get_cfg(f"campaign_tag_mode:{user_id}", "hide")
            except Exception:
                tag_mode = "hide"
            try:
                topic_links = get_cfg(f"campaign_topic_links:{user_id}", []) or []
            except Exception:
                topic_links = []
            # Default behavior: always WITHOUT tag unless user is premium AND explicitly chose "with"
            try:
                is_premium = bool(premium_active(user_id))
            except Exception:
                is_premium = False
            with_tag = bool(is_premium and str(tag_mode).lower() == "with")
            # -------------------------------------------------------------

            while True:
                if not _auto_mode_allows_now(user_id):
                    await _auto_mode_sleep(user_id, int(interval))
                    continue
                for lk in links:
                    p, mid = parse_post_link(lk)
                    if not p or not mid:
                        continue
                    if p != first_peer:
                        src = await client.get_input_entity(int(p) if str(p).lstrip("-").isdigit() else p)

                    await forward_to_groups(
                        main_bot=main_bot, admin_log_bot_unused=None, log_bot=log_bot, owner_id=owner_id,
                        user_id=user_id, session_id=session_id,
                        client=client, src=src, source_msg_id=mid, source_link=lk,
                        group_ids=gids, interval_s=interval, topic_links=topic_links, with_tag=with_tag
                    )
                    await _auto_mode_sleep(user_id, int(interval))
        except asyncio.CancelledError:
            pass
        finally:
            set_campaign_running(camp_id, 0)
            try: await client.disconnect()
            except Exception: pass

    task = asyncio.create_task(worker())
    RUNNING_TASKS[(user_id, session_id)] = task

def stop_campaign_for(user_id:int, session_id:int):
    t = RUNNING_TASKS.pop((user_id, session_id), None)
    if t and not t.cancelled(): t.cancel()
