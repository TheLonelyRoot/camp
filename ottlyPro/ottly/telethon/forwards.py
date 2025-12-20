import random
import asyncio
from telethon import errors, functions
from ..core.config import ENV
from ..core.repo import premium_active, add_metric, bump_counters, get_cfg, get_user_counters, list_sessions
from ..tg.logging_svc import send_live_log, display_name
from ..core.timeutil import now_local
from ..features.reporter import append_admin_log_row

def _extract_forwarded_msg_id(resp):
    """Try to extract the sent/forwarded message id from Telethon responses.

    Telethon may return a Message, a list/tuple, or an Updates object (e.g., from ForwardMessagesRequest).
    """
    if resp is None:
        return None
    mid = getattr(resp, "id", None)
    if mid:
        return mid
    # list/tuple of responses
    if isinstance(resp, (list, tuple)):
        for r in resp:
            mid2 = _extract_forwarded_msg_id(r)
            if mid2:
                return mid2
        return None
    updates = getattr(resp, "updates", None)
    if updates:
        for u in updates:
            # UpdateNewMessage / UpdateNewChannelMessage have .message
            m = getattr(u, "message", None)
            mid3 = getattr(m, "id", None) if m is not None else None
            if mid3:
                return mid3
            # sometimes update itself carries id
            mid4 = getattr(u, "id", None)
            if mid4:
                return mid4
    return None

async def _append_csv_row_for_send(dst_ent, username: str, public_link: str, campaign_link: str, sent_at=None):
    try:
        from ..core.timeutil import now_local
        from ..features.reporter import append_admin_log_row
        ts = (sent_at or now_local()).isoformat()
        gname = display_name(dst_ent) if dst_ent is not None else '—'
        gid = getattr(dst_ent, 'id', None) if dst_ent is not None else None
        append_admin_log_row(
            timestamp=ts,
            username=username or '',
            profile_name=username or '',
            group_name=gname,
            group_id=gid or 0,
            public_link=public_link or '—',
            campaign_link=campaign_link or '—'
        )
    except Exception:
        pass

def parse_post_link(link: str):
    """Parse a Telegram post or topic link into (peer, message_id)."""
    import re
    if not link:
        return None, None
    link = link.strip()
    # t.me/username/msgid
    m = re.match(r"^https?://t\.me/([^/]+)/([0-9]+)$", link)
    if m and m.group(1) != "c":
        return m.group(1), int(m.group(2))
    # t.me/c/internal/msgid
    m = re.match(r"^https?://t\.me/c/([0-9]+)/([0-9]+)$", link)
    if m:
        internal = m.group(1)
        msg_id = int(m.group(2))
        peer = int(f"-100{internal}")
        return peer, msg_id
    # domain=...&post=... style
    m = re.search(r"domain=([^&]+).*post=([0-9]+)", link)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


async def ensure_trial_profile(client, user_id: int):
    # keep original behavior as no-op for now
    return

def fmt_msg_public_link(ent, msg_id: int):
    if not ent:
        return "—"
    try:
        uname = getattr(ent, "username", None)
    except Exception:
        uname = None
    if uname:
        return f"https://t.me/{uname}/{msg_id}"
    gid = str(getattr(ent, "id", ""))
    if gid.startswith("-100"):
        gid = gid[4:]
    else:
        gid = gid.lstrip("-")
    return f"https://t.me/c/{gid}/{msg_id}"


def fmt_topic_msg_public_link(ent, topic_id: int, msg_id: int):
    """Build a public link for a message inside a forum topic.

    For public usernames:
        https://t.me/<username>/<topic_id>/<msg_id>

    For private/c-internal:
        https://t.me/c/<internal>/<topic_id>/<msg_id>
    """
    if not ent:
        return "—"
    try:
        uname = getattr(ent, "username", None)
    except Exception:
        uname = None
    if uname:
        return f"https://t.me/{uname}/{topic_id}/{msg_id}"
    gid = str(getattr(ent, "id", ""))
    if gid.startswith("-100"):
        gid = gid[4:]
    else:
        gid = gid.lstrip("-")
    return f"https://t.me/c/{gid}/{topic_id}/{msg_id}"

def _fallback_group_link(ent):
    if not ent:
        return "—"
    try:
        uname = getattr(ent, "username", None)
    except Exception:
        uname = None
    if uname:
        return f"https://t.me/{uname}"
    gid = str(getattr(ent, "id", ""))
    if gid.startswith("-100") and len(gid) > 4:
        return f"https://t.me/c/{gid[4:]}"
    return "—"

def _parse_topic_link(link: str):
    """Accept t.me/<username>/<msgid> or t.me/c/<internal>/<msgid>."""
    import re
    if not link:
        return None
    link = link.strip()
    m = re.match(r"^https?://t\.me/([^/]+)/([0-9]+)$", link)
    if m and m.group(1) != "c":
        peer = m.group(1)
        top_id = int(m.group(2))
        return peer, top_id
    m = re.match(r"^https?://t\.me/c/([0-9]+)/([0-9]+)$", link)
    if m:
        internal = m.group(1)
        top_id = int(m.group(2))
        peer = int(f"-100{internal}")
        return peer, top_id
    return None

async def forward_to_groups(
    main_bot, admin_log_bot_unused, log_bot, owner_id: int,
    user_id: int, session_id: int, client, src, source_msg_id: int, source_link: str,
    group_ids: list, interval_s: int,
    *, topic_links=None, with_tag: bool = False
):
    """Forward message to groups and then topic links; keep logs & metrics."""
    if topic_links is None:
        topic_links = []

    # Premium gate
    if (with_tag or len(topic_links) > 0) and not premium_active(user_id):
        try:
            await send_live_log(log_bot, user_id, "🔒 Premium required for with-tag / topics. Sent only basic group forwards.")
        except Exception:
            pass
        topic_links = []
        with_tag = False

    me = await client.get_me()

    # Determine which account index (#1, #2, ...) and phone number are being used
    account_index = None
    phone_number = getattr(me, "phone", None) or "—"
    try:
        sessions = list_sessions(user_id)
    except Exception:
        sessions = []
    if sessions:
        for idx_session, (sid, phone, session_path, is_active) in enumerate(sessions, start=1):
            try:
                sid_int = int(sid)
            except Exception:
                sid_int = sid
            if sid_int == session_id:
                account_index = idx_session
                if phone:
                    phone_number = phone
                break
    if account_index is None:
        account_index = 1
    source_msg = await client.get_messages(src, ids=source_msg_id)
    source_text = (source_msg.message or "").strip() if source_msg else ""
    is_env_ad_match = int(source_text == (ENV.ENV_AD_MESSAGE or "").strip())

    # choose random delay range per target
    if premium_active(user_id):
        try:
            cfg = get_cfg(f"campaign_target_delay:{user_id}", None)
        except Exception:
            cfg = None
        if isinstance(cfg, (list, tuple)) and len(cfg) == 2:
            try:
                min_delay = int(cfg[0])
                max_delay = int(cfg[1])
            except Exception:
                min_delay, max_delay = 5, 90
        else:
            min_delay, max_delay = 5, 90
    else:
        min_delay, max_delay = 10, 45

    async def _sleep_between_targets():
        import random as _r
        delay = _r.randint(min_delay, max_delay)
        await asyncio.sleep(delay)

    
    # Pre-compute total number of targets (groups + topics)
    try:
        total_targets = len(group_ids) + (len(topic_links) if topic_links else 0)
    except Exception:
        total_targets = len(group_ids)

    async def log_and_metrics(dst_ent, dst_id, public_link, status_text, fail_reason, sent_post_link=None, *, group_idx=None, total_targets=None):
        gname = display_name(dst_ent) if dst_ent else "—"
        total_sent_local = None

        # Metrics and CSV logging (unchanged structure)
        try:
            add_metric(user_id, session_id, int(dst_id) if dst_id is not None else 0, status_text == "success", is_env_ad_match)
            bump_counters(user_id, session_id, sent=(status_text == "success"), failed=(status_text != "success"))
            try:
                total_sent_local, _env_dummy = get_user_counters(user_id)
            except Exception:
                total_sent_local = None
            append_admin_log_row(
                user_id=user_id,
                session_id=session_id,
                status=status_text,
                fail_reason=(fail_reason or "—"),
                from_user=display_name(me),
                group_name=gname,
                group_id=int(dst_id) if dst_id is not None else 0,
                public_link=public_link,
                campaign_link=source_link
            )
        except Exception:
            # metrics / CSV failures must not stop the campaign loop
            pass

        # Human readable live log line with extended info
        try:
            date_str = now_local().strftime("%d %B %Y")
            time_str = now_local().strftime("%I:%M %p")
            post_link_str = sent_post_link or "—"

            # group index / total (with topics)
            if group_idx is not None and total_targets:
                group_idx_str = f"{group_idx}/{total_targets}"
            else:
                group_idx_str = "—"

            # which account index (#1, #2, ...)
            account_idx_str = f"#{account_index}" if 'account_index' in locals() or 'account_index' in globals() else "—"
            phone_str = phone_number if ('phone_number' in locals() or 'phone_number' in globals()) else "—"
            total_sent_str = str(total_sent_local) if total_sent_local is not None else "—"

            plain = (
                f"message sent | {gname} {date_str} | {time_str} | {source_link} | {public_link} | {post_link_str} | "
                f"@{ENV.MAIN_BOT_USERNAME} | {group_idx_str} | {account_idx_str} | {phone_str} | "
                f"{status_text} | {fail_reason} | {total_sent_str}"
            )
            await send_live_log(log_bot, user_id, plain)
        except Exception:
            # Logging failures must not stop the campaign loop
            pass

    # 1) groups
    for idx_group, gid in enumerate(group_ids, start=1):
        status_text = "success"
        fail_reason = "—"
        glink = "—"
        dst_ent = None
        try:
            await ensure_trial_profile(client, user_id)
            dst = await client.get_input_entity(gid)
            dst_ent = await client.get_entity(gid)
            # get original message once per group send
            orig = await client.get_messages(src, ids=source_msg_id)
            if orig is None:
                raise RuntimeError("Source message not found")
            # when with_tag=True keep original forward tag; otherwise copy to hide sender
            if with_tag:
                fwd = await client.forward_messages(dst, source_msg_id, from_peer=src)
                if isinstance(fwd, (list, tuple)) and fwd:
                    fwd = fwd[0]
            else:
                # try to hide tag for plain-text posts, but keep content/buttons the same
                if getattr(orig, "message", None) and not getattr(orig, "media", None):
                    fwd = await client.send_message(dst, orig.message, buttons=getattr(orig, "reply_markup", None))
                else:
                    fwd = await client.send_message(dst, orig, buttons=getattr(orig, "reply_markup", None))
            fwd_msg_id = _extract_forwarded_msg_id(fwd)
            post_link = "—"
            try:
                if dst_ent is not None and fwd_msg_id:
                    post_link = fmt_msg_public_link(dst_ent, fwd_msg_id)
            except Exception:
                post_link = "—"

            try:
                inv = await client(functions.messages.ExportChatInviteRequest(peer=gid))
                glink = getattr(inv, "link", None) or "—"
            except Exception:
                glink = "—"
            if glink == "—" and dst_ent is not None:
                glink = _fallback_group_link(dst_ent)
            if glink == "—" and dst_ent is not None and fwd_msg_id:
                glink = fmt_msg_public_link(dst_ent, fwd_msg_id)
        except errors.ChatForwardsRestrictedError:
            status_text = "failed"
            fail_reason = "Forward restricted by source"
        except errors.ForbiddenError as fe:
            status_text = "failed"
            fail_reason = f"Forbidden: {fe}"
        except errors.MessageIdInvalidError:
            status_text = "failed"
            fail_reason = "Message not found"
        except errors.FloodWaitError as fw:
            status_text = "failed"
            fail_reason = f"Flood wait {fw.seconds}s"
            await asyncio.sleep(fw.seconds + 1)
        except Exception as ge:
            status_text = "failed"
            fail_reason = f"{ge}"
        await log_and_metrics(dst_ent, gid, glink, status_text, fail_reason, sent_post_link=post_link, group_idx=idx_group, total_targets=total_targets)
        await _sleep_between_targets()

    # 2) topics
    for offset_topic, ln in enumerate(topic_links, start=1):
        current_idx = len(group_ids) + offset_topic
        parsed = _parse_topic_link(ln)
        if not parsed:
            continue
        peer, top_id = parsed
        status_text = "success"
        fail_reason = "—"
        dst_ent = None
        topic_link = ln
        post_link = "—"
        try:
            dst_ent = await client.get_entity(peer)
            # get original message once per topic send
            orig = await client.get_messages(src, ids=source_msg_id)
            if orig is None:
                raise RuntimeError("Source message not found")
            # send inside the specific topic using top_msg_id when with_tag=True
            if with_tag:
                fwd = await client(functions.messages.ForwardMessagesRequest(
                    from_peer=src,
                    id=[source_msg_id],
                    to_peer=peer,
                    top_msg_id=top_id,
                    drop_author=False,
                    drop_media_captions=False
                ))
                if isinstance(fwd, (list, tuple)) and fwd:
                    fwd = fwd[0]
            else:
                fwd = await client.send_message(peer, orig, reply_to=top_id)
            # Build exact forum-post link: /<topic_id>/<message_id>
            try:
                fwd_msg_id = _extract_forwarded_msg_id(fwd)
                if dst_ent is not None and fwd_msg_id:
                    post_link = fmt_topic_msg_public_link(dst_ent, top_id, fwd_msg_id)
            except Exception:
                post_link = "—"
        except errors.ChatForwardsRestrictedError:
            status_text = "failed"
            fail_reason = "Forward restricted by source"
        except errors.FloodWaitError as fw:
            status_text = "failed"
            fail_reason = f"Flood wait {fw.seconds}s"
            await asyncio.sleep(fw.seconds + 1)
        except Exception as ge:
            status_text = "failed"
            fail_reason = f"{ge}"
        dst_id = getattr(dst_ent, "id", None) if dst_ent is not None else None
        await log_and_metrics(dst_ent, dst_id, topic_link, status_text, fail_reason, sent_post_link=post_link, group_idx=current_idx, total_targets=total_targets)
        await _sleep_between_targets()
