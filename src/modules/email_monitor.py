"""
Email Monitor — v2 three-layer notification system.

Layer 1: Poller — fetch new emails, triage, route to immediate push or digest queue.
Layer 2: Digest — send batched email digest card when interval elapses.
Layer 3: Bot conversation — handled by existing bot.py (no code here).

Entry point: poll_and_notify(graph, owner_graph, data_dir, settings, chat_id)
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.modules.crm import load_crm
from src.modules.screener import screen_emails
from src.modules.profile import load_profile_context


_NOISE_SENDERS = re.compile(
    r"(noreply|no[_\-]reply|donotreply|do[_\-]not[_\-]reply|"
    r"notifications?@|mailer[-_]daemon|bounce@|postmaster@)",
    re.IGNORECASE,
)
_MAX_PROCESSED_IDS = 1000
_DEFAULT_DIGEST_INTERVAL_H = 2
_DEFAULT_ACTIVE_HOURS = [8, 18]


# ── State helpers ─────────────────────────────────────────────────────────

def _load_monitor_state(data_dir: Path) -> dict:
    path = data_dir / "email_monitor.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "last_checked_ts": "",
        "last_digest_ts": "",
        "processed_conv_ids": [],
        "pending_digest": [],
        "pending_priority_followup": [],
        "last_notified_emails": [],
    }


def _save_monitor_state(data_dir: Path, state: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "email_monitor.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Address helpers ───────────────────────────────────────────────────────

def _from_addr(msg: dict) -> str:
    return ((msg.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()


def _from_name(msg: dict) -> str:
    ea = (msg.get("from") or {}).get("emailAddress") or {}
    return (ea.get("name") or "").strip() or ea.get("address", "").split("@")[0]


# ── Noise filter ──────────────────────────────────────────────────────────

def _noise_filter(emails: list, processed_conv_ids: set) -> list:
    """Rule-based pre-filter (zero API cost): removes automated senders and seen conversations."""
    result = []
    for m in emails:
        addr = _from_addr(m)
        conv_id = m.get("conversationId") or m.get("id", "")
        if _NOISE_SENDERS.search(addr):
            continue
        if conv_id in processed_conv_ids:
            continue
        result.append(m)
    return result


# ── Context loading ───────────────────────────────────────────────────────

def _load_email_context(emails: list, owner_graph, data_dir: Path) -> list:
    """Enrich each email with CRM priority and upcoming calendar notes. Zero API cost."""
    crm = load_crm(data_dir).get("contacts", {})

    cal_attendees: dict = {}
    try:
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=48)
        events = owner_graph.get_calendar_view(
            now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            top=20,
        )
        for evt in events:
            for att in (evt.get("attendees") or []):
                addr = ((att.get("emailAddress") or {}).get("address") or "").lower()
                if addr:
                    cal_attendees.setdefault(addr, []).append(evt.get("subject") or "(untitled)")
    except Exception:
        pass

    enriched = []
    for m in emails:
        addr = _from_addr(m)
        contact = crm.get(addr, {})
        meetings = cal_attendees.get(addr, [])
        enriched.append({
            **m,
            "_crm_priority": contact.get("priority", ""),
            "_crm_company": contact.get("company", ""),
            "_crm_name": contact.get("name", ""),
            "_calendar_note": f"Meeting soon: {', '.join(meetings[:2])}" if meetings else "",
        })
    return enriched


# ── AI triage ─────────────────────────────────────────────────────────────

def _ai_triage(emails: list, settings: dict, ai, data_dir: Path = None) -> list:
    """
    Single batch prompt → classify each email as priority / review / skip.
    Returns emails with _importance, _ai_reason, _ai_action added.
    Reads data_dir/instructions/email_monitor.md for user-defined triage rules.
    """
    if not emails:
        return []

    bc = load_profile_context(data_dir) if data_dir else ""
    display_name = settings.get("display_name", "the executive")

    instruction = ""
    if data_dir:
        instr_path = Path(data_dir) / "instructions" / "email_monitor.md"
        if instr_path.exists():
            try:
                instruction = instr_path.read_text().strip()
            except Exception:
                pass

    lines = []
    for i, m in enumerate(emails):
        crm_note = ""
        if m.get("_crm_priority"):
            crm_note += f" [CRM: {m['_crm_priority']} priority"
            if m.get("_crm_company"):
                crm_note += f", {m['_crm_company']}"
            crm_note += "]"
        if m.get("_calendar_note"):
            crm_note += f" [{m['_calendar_note']}]"
        lines.append(
            f"[{i}] From: {_from_name(m)} <{_from_addr(m)}>{crm_note}\n"
            f"     Subject: {(m.get('subject') or '(no subject)')[:120]}\n"
            f"     Preview: {(m.get('bodyPreview') or '')[:200]}"
        )

    bc_block = f"Business context:\n{bc.strip()}\n\n" if bc.strip() else ""
    instr_block = f"Custom triage rules from the user:\n{instruction}\n\n" if instruction else ""

    prompt = f"""You are an email triage assistant for {display_name}, a busy executive.

{bc_block}{instr_block}These emails have already passed an automated noise filter. Classify each as:
- priority: written by a real person about a real business matter (client, deal, money, meeting, decision)
- review: written by a real person but lower urgency, OR a newsletter/digest with real content
- skip: ONLY for clearly automated messages (no-reply alerts, system notifications, delivery status)

IMPORTANT: When in doubt between priority/review and skip, always choose review.
Do NOT skip an email just because the sender is unknown or the tone is unusual — err on the side of showing it.

Respond with a JSON array, one object per email in the same order:
[{{"idx":0,"importance":"priority","reason":"one sentence","action":"suggested action"}}]

Emails to triage:
{chr(10).join(lines)}"""

    try:
        raw = ai.extract_json(prompt)
        results = json.loads(raw)
        by_idx = {r["idx"]: r for r in results if isinstance(r, dict) and "idx" in r}
    except Exception as e:
        print(f"[EmailMonitor] triage parse error: {e}")
        by_idx = {}

    out = []
    for i, m in enumerate(emails):
        triage = by_idx.get(i, {})
        out.append({
            **m,
            "_importance": triage.get("importance", "review"),
            "_ai_reason": triage.get("reason", ""),
            "_ai_action": triage.get("action", ""),
        })
    return out


# ── Relative time helper ──────────────────────────────────────────────────

def _relative_time(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        mins = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
        if mins < 60:
            return f"{mins}m ago"
        if mins < 1440:
            return f"{mins // 60}h ago"
        return f"{mins // 1440}d ago"
    except Exception:
        return iso_ts[:10] if iso_ts else ""


# ── Card builders ─────────────────────────────────────────────────────────

def _build_email_card(email_item: dict) -> dict:
    """Single priority email Adaptive Card. No Action buttons — user replies in chat."""
    from_name = _from_name(email_item) or email_item.get("_crm_name") or "Unknown"
    company = email_item.get("_crm_company", "")
    crm_prio = email_item.get("_crm_priority", "")
    subject = (email_item.get("subject") or "(no subject)")[:120]
    received = _relative_time(email_item.get("receivedDateTime", ""))
    ai_reason = email_item.get("_ai_reason", "")
    cal_note = email_item.get("_calendar_note", "")

    from_val = from_name
    if company:
        from_val += f" · {company}"
    if crm_prio:
        label = {"high": "🔴 High priority", "medium": "🟡 Medium priority", "low": "⚪ Low priority"}.get(crm_prio, crm_prio)
        from_val += f" · {label}"

    body: list = [
        {"type": "TextBlock", "text": "📧 New Email — Priority", "weight": "Bolder", "size": "Medium"},
        {
            "type": "FactSet",
            "facts": [
                {"title": "From", "value": from_val},
                {"title": "Subject", "value": subject},
                {"title": "Received", "value": received},
            ],
        },
    ]

    if ai_reason:
        body.append({"type": "TextBlock", "text": f"💡 {ai_reason}", "wrap": True, "separator": True})

    if cal_note:
        body.append({"type": "TextBlock", "text": f"📅 {cal_note}", "wrap": True, "isSubtle": True})

    body.append({
        "type": "TextBlock",
        "text": "Reply here to draft a response or ask about this email.",
        "wrap": True,
        "isSubtle": True,
        "separator": True,
    })

    actions = []
    web_link = email_item.get("webLink") or email_item.get("_web_link", "")
    if web_link:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "📬 Open in Outlook",
            "url": web_link,
        })

    card: dict = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _build_digest_card(emails: list) -> dict:
    """Multi-email digest Adaptive Card with priority and review buckets."""
    priority = [e for e in emails if e.get("_importance") == "priority"]
    review   = [e for e in emails if e.get("_importance") == "review"]

    body: list = [
        {
            "type": "TextBlock",
            "text": f"📧 Email Digest — {len(emails)} new email{'s' if len(emails) != 1 else ''}",
            "weight": "Bolder",
            "size": "Medium",
        }
    ]

    if priority:
        body.append({
            "type": "TextBlock",
            "text": f"🔴 Priority ({len(priority)})",
            "weight": "Bolder",
            "separator": True,
        })
        for e in priority[:5]:
            name = _from_name(e) or e.get("_crm_name") or "Unknown"
            company = e.get("_crm_company", "")
            subject = (e.get("subject") or "(no subject)")[:80]
            received = _relative_time(e.get("receivedDateTime", ""))
            label = f"**{name}**"
            if company:
                label += f" ({company})"
            label += f' — "{subject}" — {received}'
            body.append({"type": "TextBlock", "text": f"• {label}", "wrap": True})
            if e.get("_ai_reason"):
                body.append({"type": "TextBlock", "text": f"  {e['_ai_reason']}", "wrap": True, "isSubtle": True})

    if review:
        body.append({
            "type": "TextBlock",
            "text": f"📋 Review ({len(review)})",
            "weight": "Bolder",
            "separator": True,
        })
        for e in review[:5]:
            name = _from_name(e) or "Unknown"
            subject = (e.get("subject") or "(no subject)")[:80]
            body.append({"type": "TextBlock", "text": f'• {name} — "{subject}"', "wrap": True})
        if len(review) > 5:
            body.append({"type": "TextBlock", "text": f"  ...and {len(review) - 5} more", "isSubtle": True})

    body.append({
        "type": "TextBlock",
        "text": "Reply here to ask about any email or draft a response.",
        "wrap": True,
        "isSubtle": True,
        "separator": True,
    })

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
        "body": body,
    }


# ── Digest timing ─────────────────────────────────────────────────────────

def _should_send_digest(monitor_state: dict, settings: dict) -> bool:
    """True when digest interval has elapsed, within active hours, and queue is non-empty."""
    interval_h = float(settings.get("email_digest_interval_hours", _DEFAULT_DIGEST_INTERVAL_H))
    if interval_h <= 0:
        return False

    if not monitor_state.get("pending_digest") and not monitor_state.get("pending_priority_followup"):
        return False

    active = settings.get("email_active_hours") or _DEFAULT_ACTIVE_HOURS
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(settings.get("timezone", "UTC"))
        local_hour = datetime.now(tz).hour
    except Exception:
        local_hour = datetime.now(timezone.utc).hour

    if not (active[0] <= local_hour < active[1]):
        return False

    last_ts = monitor_state.get("last_digest_ts") or ""
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            elapsed_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if elapsed_h < interval_h:
                return False
        except Exception:
            pass

    return True


# ── Card sending ──────────────────────────────────────────────────────────

def _send_adaptive_card(graph, chat_id: str, card: dict) -> None:
    """Send an Adaptive Card to a Teams 1:1 chat."""
    card_id = uuid.uuid4().hex
    graph.post(f"/me/chats/{chat_id}/messages", {
        "body": {
            "contentType": "html",
            "content": f'<attachment id="{card_id}"></attachment>',
        },
        "attachments": [
            {
                "id": card_id,
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": json.dumps(card),
            }
        ],
    })


# ── Priority follow-up tracking ───────────────────────────────────────────

def _check_replied(followups: list, owner_graph) -> list:
    """
    Return only items from followups that have NOT been replied to.
    Also drops items older than 7 days (avoids indefinite accumulation).
    Checks SentItems for a message in the same conversationId.
    """
    if not followups:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    still_pending = []
    for item in followups:
        pushed_str = item.get("pushed_at", "")
        if pushed_str:
            try:
                if datetime.fromisoformat(pushed_str.replace("Z", "+00:00")) < cutoff:
                    continue  # too old — drop
            except Exception:
                pass
        conv_id = item.get("conv_id", "")
        if not conv_id:
            continue
        try:
            sent = owner_graph.get_messages(
                top=1,
                filter=f"conversationId eq '{conv_id}'",
                folder="SentItems",
            )
            if sent:
                continue  # user replied — remove from followup
        except Exception:
            pass  # on error, keep item
        still_pending.append(item)
    return still_pending


# ── Digest layer ──────────────────────────────────────────────────────────

def _maybe_send_digest(graph, chat_id: str, monitor_state: dict, settings: dict) -> None:
    """Send digest card if interval has elapsed and there are pending items or unreplied priority emails."""
    if not _should_send_digest(monitor_state, settings):
        return

    pending = list(monitor_state.get("pending_digest") or [])
    followups = list(monitor_state.get("pending_priority_followup") or [])

    # Convert followup items to digest-compatible format with "unreplied" label
    followup_items = [
        {
            "_importance": "priority",
            "_ai_reason": "⏰ Awaiting your reply",
            "from_name": f.get("from_name", ""),
            "subject": f.get("subject", ""),
            "receivedDateTime": f.get("pushed_at", ""),
            "_crm_company": f.get("_crm_company", ""),
        }
        for f in followups
    ]

    all_items = followup_items + pending
    if not all_items:
        return

    try:
        card = _build_digest_card(all_items)
        _send_adaptive_card(graph, chat_id, card)
        print(f"[EmailMonitor] Digest sent: {len(all_items)} items ({len(followup_items)} unreplied, {len(pending)} new)")
        monitor_state["pending_digest"] = []
        monitor_state["last_digest_ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # pending_priority_followup is intentionally NOT cleared — it persists until replied or 7 days old
    except Exception as e:
        print(f"[EmailMonitor] Digest send failed: {e}")


# ── Main entry point ──────────────────────────────────────────────────────

def poll_and_notify(graph, owner_graph, data_dir: Path, settings: dict, chat_id: str) -> None:
    """
    Layer 1 + 2: poll owner's inbox for new emails, triage, notify via Teams.

    graph       — bot's GraphClient (sends messages)
    owner_graph — owner's GraphClient (reads email + calendar)
    data_dir    — Path to .data/{owner_uid}/
    settings    — owner's settings dict
    chat_id     — Teams 1:1 chat ID between bot and owner
    """
    if not owner_graph or not chat_id:
        return

    data_dir = Path(data_dir)

    # Pull email-monitor config from schedules.json and overlay onto settings
    # so downstream functions (digest timing, realtime push) use the user's preferences.
    try:
        from src.modules.schedules import load_schedules
        em = load_schedules(data_dir).get("email_monitor", {})
        settings = dict(settings or {})
        if "interval_minutes" in em:
            settings["email_digest_interval_hours"] = float(em["interval_minutes"]) / 60.0
        if "active_start" in em and "active_end" in em:
            try:
                start_h = int(str(em["active_start"]).split(":")[0])
                end_h   = int(str(em["active_end"]).split(":")[0])
                settings["email_active_hours"] = [start_h, end_h]
            except Exception:
                pass
        if "priority_immediate" in em:
            settings["email_realtime_push"] = bool(em["priority_immediate"])
    except Exception as e:
        print(f"[EmailMonitor] Schedule overlay failed: {e}")

    monitor_state = _load_monitor_state(data_dir)
    processed_ids = set(monitor_state.get("processed_conv_ids") or [])

    # Prune priority followups that have already been replied to
    followups = monitor_state.get("pending_priority_followup") or []
    if followups:
        try:
            monitor_state["pending_priority_followup"] = _check_replied(followups, owner_graph)
        except Exception as e:
            print(f"[EmailMonitor] Reply check error: {e}")

    last_ts = monitor_state.get("last_checked_ts") or ""

    # First run: mark current time as baseline, send no notifications
    if not last_ts:
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        monitor_state["last_checked_ts"] = now_ts
        _save_monitor_state(data_dir, monitor_state)
        print(f"[EmailMonitor] First run — fast-forwarded to {now_ts}")
        return

    # Fetch emails since last check
    try:
        # Inbox only — excludes Drafts/Sent/Junk.
        # Use 'ge' not 'gt' so emails at exactly last_checked_ts are not missed;
        # processed_conv_ids handles deduplication.
        raw_emails = owner_graph.get_messages(
            top=50,
            filter=f"receivedDateTime ge {last_ts}",
            orderby="receivedDateTime asc",
            folder="Inbox",
        )
    except Exception as e:
        print(f"[EmailMonitor] Fetch failed: {e}")
        _maybe_send_digest(graph, chat_id, monitor_state, settings)
        _save_monitor_state(data_dir, monitor_state)
        return

    newest_ts = max(
        (m.get("receivedDateTime", "") for m in raw_emails),
        default=last_ts,
    )

    if raw_emails:
        # Build ignored_emails from CRM
        ignored_emails: set = set()
        try:
            crm_data = load_crm(data_dir)
            ignored_emails = {
                email for email, c in crm_data.get("contacts", {}).items() if c.get("ignore")
            }
        except Exception:
            pass

        from src.ai import AIClient
        ai = AIClient()

        # Screen (CLAUDE.md Principle 5)
        try:
            screened = screen_emails(
                messages=raw_emails,
                ai=ai,
                ignored_emails=ignored_emails,
                business_context=load_profile_context(data_dir),
                display_name=settings.get("display_name", "the executive"),
            )
            visible = [m for m in screened if not m.get("screened_out")]
        except Exception as e:
            print(f"[EmailMonitor] Screener error: {e}")
            visible = raw_emails

        # Rule-based noise filter
        filtered = _noise_filter(visible, processed_ids)

        # Enrich with CRM + calendar context
        try:
            enriched = _load_email_context(filtered, owner_graph, data_dir)
        except Exception as e:
            print(f"[EmailMonitor] Context load error: {e}")
            enriched = filtered

        # Layer 1: CRM hard rules (zero API cost)
        crm_classified, needs_triage = [], []
        for m in enriched:
            p = m.get("_crm_priority", "")
            if p == "high":
                crm_classified.append({
                    **m,
                    "_importance": "priority",
                    "_ai_reason": "CRM: high priority contact",
                    "_ai_action": "",
                })
                print(f"[EmailMonitor] CRM forced priority: {_from_addr(m)}")
            elif p == "low":
                crm_classified.append({
                    **m,
                    "_importance": "review",
                    "_ai_reason": "CRM: low priority contact",
                    "_ai_action": "",
                })
                print(f"[EmailMonitor] CRM forced review: {_from_addr(m)}")
            else:
                needs_triage.append(m)

        # Layer 2: AI triage for contacts without a CRM rule
        if needs_triage:
            try:
                ai_triaged = _ai_triage(needs_triage, settings, ai, data_dir=data_dir)
            except Exception as e:
                print(f"[EmailMonitor] Triage error: {e}")
                ai_triaged = [{**m, "_importance": "review", "_ai_reason": "", "_ai_action": ""} for m in needs_triage]
        else:
            ai_triaged = []
        triaged = crm_classified + ai_triaged

        realtime_push = settings.get("email_realtime_push", True)
        if isinstance(realtime_push, str):
            realtime_push = realtime_push.lower() not in ("false", "0", "no")

        notified = list(monitor_state.get("last_notified_emails") or [])

        for email_item in triaged:
            importance = email_item.get("_importance", "review")
            conv_id = email_item.get("conversationId") or email_item.get("id", "")
            processed_ids.add(conv_id)

            if importance == "skip":
                continue

            summary = {
                "from": _from_addr(email_item),
                "subject": email_item.get("subject", ""),
                "conv_id": conv_id,
            }

            if importance == "priority" and realtime_push:
                try:
                    card = _build_email_card(email_item)
                    _send_adaptive_card(graph, chat_id, card)
                    notified.append(summary)
                    print(f"[EmailMonitor] Priority push: {_from_addr(email_item)} — {email_item.get('subject','')[:60]}")
                    # Track for follow-up reminders (appears in digest if user hasn't replied)
                    monitor_state.setdefault("pending_priority_followup", []).append({
                        "conv_id": conv_id,
                        "from": _from_addr(email_item),
                        "from_name": _from_name(email_item),
                        "subject": email_item.get("subject", ""),
                        "pushed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "_crm_company": email_item.get("_crm_company", ""),
                        "_ai_reason": email_item.get("_ai_reason", ""),
                    })
                except Exception as e:
                    print(f"[EmailMonitor] Card send failed: {e}")
            else:
                monitor_state.setdefault("pending_digest", []).append({
                    **summary,
                    "received": email_item.get("receivedDateTime", ""),
                    "importance": importance,
                    "_importance": importance,
                    "_ai_reason": email_item.get("_ai_reason", ""),
                    "_ai_action": email_item.get("_ai_action", ""),
                    "_crm_company": email_item.get("_crm_company", ""),
                    "crm_priority": email_item.get("_crm_priority", ""),
                    "calendar_note": email_item.get("_calendar_note", ""),
                    "from_name": _from_name(email_item),
                    "from_email": _from_addr(email_item),
                })
                notified.append(summary)

        if len(processed_ids) > _MAX_PROCESSED_IDS:
            processed_ids = set(list(processed_ids)[-_MAX_PROCESSED_IDS:])

        monitor_state["processed_conv_ids"] = list(processed_ids)
        monitor_state["last_notified_emails"] = notified[-20:]

    monitor_state["last_checked_ts"] = newest_ts

    _maybe_send_digest(graph, chat_id, monitor_state, settings)
    _save_monitor_state(data_dir, monitor_state)
