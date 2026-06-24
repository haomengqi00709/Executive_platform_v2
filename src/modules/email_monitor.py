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
    # Source of truth is the per-user SQLite store (atomic, no torn whole-file writes); it lazily
    # imports the legacy email_monitor.json on first access and keeps it synced as a projection.
    from src.modules import email_store
    return email_store.get_poller_state(data_dir)


def _save_monitor_state(data_dir: Path, state: dict) -> None:
    from src.modules import email_store
    email_store.save_poller_state(data_dir, state)


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
[{{"idx":0,"importance":"priority","reason":"why this is priority/review/skip","summary":"one-sentence summary of what the email is actually about","action":"suggested action"}}]

- summary: a single sentence describing the actual content of the email (what they're asking, telling, or sharing). Concrete, no jargon.

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
            "_ai_summary": triage.get("summary", ""),
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


def _build_digest_html(emails: list, since_time_str: str = "") -> str:
    """Build digest as an HTML message — one Teams message containing all emails grouped by importance.
    Each email is in its own <p> so Teams renders natural paragraph spacing between entries."""
    priority = [e for e in emails if e.get("_importance") == "priority"]
    review   = [e for e in emails if e.get("_importance") == "review"]

    n = len(emails)
    suffix = "s" if n != 1 else ""
    overview = f"<b>📧 Email Digest — {n} email{suffix}"
    if since_time_str:
        overview += f" since {since_time_str}"
    overview += "</b>"
    if priority:
        overview += f" · {len(priority)} awaiting reply"

    parts = [f"<p>{overview}</p>"]

    def _email_block(e: dict, with_company: bool = True) -> str:
        name = e.get("from_name") or e.get("_crm_name") or "Unknown"
        subject = (e.get("subject") or "(no subject)")[:120]
        label = f"<b>{name}</b>"
        company = e.get("_crm_company", "") if with_company else ""
        if company:
            label += f" ({company})"
        received = _relative_time(e.get("receivedDateTime", ""))
        time_part = f" · {received}" if received else ""
        head = f'{label} — "{subject}"{time_part}'
        summary = e.get("_ai_summary") or e.get("_ai_reason", "")
        if summary:
            return f"<p>{head}<br><i>{summary}</i></p>"
        return f"<p>{head}</p>"

    if priority:
        parts.append(f"<p><b>🔴 Priority ({len(priority)})</b></p>")
        for e in priority[:10]:
            parts.append(_email_block(e, with_company=True))

    if review:
        parts.append(f"<p><b>📋 Review ({len(review)})</b></p>")
        for e in review[:10]:
            parts.append(_email_block(e, with_company=False))
        if len(review) > 10:
            parts.append(f"<p><i>...and {len(review) - 10} more</i></p>")

    parts.append("<p><i>Reply here to ask about any email or draft a response.</i></p>")
    return "".join(parts)


# ── Digest timing ─────────────────────────────────────────────────────────

def _load_reply_needed(data_dir: Path) -> dict:
    path = Path(data_dir) / "results" / "reply_needed.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_reply_needed(data_dir: Path, data: dict) -> None:
    """Write reply_needed.json. Atomic via tmp file."""
    path = Path(data_dir) / "results" / "reply_needed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _undigested_items(data_dir: Path, pushed_ids: set | None = None) -> list:
    """reply_needed items not yet digested AND not already realtime-pushed.
    pushed_ids = monitor_state['realtime_pushed_ids'] (Graph message ids) — those were
    surfaced via the immediate Priority card, so they must never appear in the digest."""
    data = _load_reply_needed(data_dir)
    return [
        it for it in (data.get("items") or [])
        if not it.get("digested_at")
        and (not pushed_ids or it.get("email_id") not in pushed_ids)
    ]


def _should_send_digest(data_dir: Path, monitor_state: dict, settings: dict) -> bool:
    """True when digest interval has elapsed, within active hours,
    and reply_needed.json has at least one item with empty digested_at."""
    interval_h = float(settings.get("email_digest_interval_hours", _DEFAULT_DIGEST_INTERVAL_H))
    if interval_h <= 0:
        return False

    pushed_ids = set(monitor_state.get("realtime_pushed_ids") or [])
    if not _undigested_items(data_dir, pushed_ids):
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

def _reply_needed_to_digest_item(it: dict) -> dict:
    """Map a reply_needed item into the field shape _build_digest_html expects."""
    priority = it.get("priority", "medium")
    return {
        "_importance":      "priority" if priority == "high" else "review",
        "_ai_summary":      it.get("reason", ""),
        "from_name":        it.get("from_name", ""),
        "subject":          it.get("subject", ""),
        "receivedDateTime": it.get("received", ""),
        "_crm_company":     ((it.get("contact") or {}).get("company") or ""),
        "_email_id":        it.get("email_id", ""),
    }


def _maybe_send_digest(graph, chat_id: str, data_dir: Path, monitor_state: dict, settings: dict) -> None:
    """Send digest of reply_needed items that haven't been mentioned yet.
    After sending, stamps digested_at on each item so they're not repeated."""
    if not _should_send_digest(data_dir, monitor_state, settings):
        return

    pushed_ids = set(monitor_state.get("realtime_pushed_ids") or [])
    rn = _load_reply_needed(data_dir)
    items = rn.get("items") or []
    pending = [
        it for it in items
        if not it.get("digested_at") and it.get("email_id") not in pushed_ids
    ]
    if not pending:
        return

    mapped = [_reply_needed_to_digest_item(it) for it in pending]

    since_str = ""
    last_ts = monitor_state.get("last_digest_ts") or ""
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            since_str = last_dt.strftime("%-I:%M %p")
        except Exception:
            pass

    try:
        html = _build_digest_html(mapped, since_time_str=since_str)
        graph.send_html_message(chat_id, html)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Stamp digested_at on the items we just sent AND on any already-realtime-pushed
        # items still unstamped — so a pushed email is permanently kept out of the digest
        # (digested_at survives reply_needed rebuilds) even if its id later ages out of
        # realtime_pushed_ids.
        sent_ids = {it.get("email_id") for it in pending if it.get("email_id")}
        for it in items:
            eid = it.get("email_id")
            if not it.get("digested_at") and (eid in sent_ids or eid in pushed_ids):
                it["digested_at"] = now_iso
        rn["items"] = items
        _save_reply_needed(data_dir, rn)
        monitor_state["last_digest_ts"] = now_iso
        print(f"[EmailMonitor] Digest sent: {len(pending)} items")
    except Exception as e:
        print(f"[EmailMonitor] Digest send failed: {e}")


# ── Expiry warning ────────────────────────────────────────────────────────

def _maybe_send_expiry_warning(graph, chat_id: str, data_dir: Path,
                                monitor_state: dict, settings: dict) -> None:
    """Day-before-expiry heads-up: fire once daily at active_end - 2h
    when reply_needed items are 13-14 days old (will drop off the next scan)."""
    active = settings.get("email_active_hours") or _DEFAULT_ACTIVE_HOURS
    target_hour = max(0, int(active[1]) - 2)

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(settings.get("timezone", "UTC"))
        now_local = datetime.now(tz)
    except Exception:
        now_local = datetime.now(timezone.utc)

    if now_local.hour != target_hour:
        return

    today_key = now_local.strftime("%Y-%m-%d")
    if monitor_state.get("last_expiry_warning_date") == today_key:
        return

    items = (_load_reply_needed(data_dir).get("items") or [])
    if not items:
        return

    now_utc = datetime.now(timezone.utc)
    expiring: list = []
    for it in items:
        received_str = it.get("received", "")
        if not received_str:
            continue
        try:
            received_dt = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
        except Exception:
            continue
        age_days = (now_utc - received_dt).total_seconds() / 86400.0
        if 13.0 <= age_days < 14.0:
            expiring.append(it)

    if not expiring:
        monitor_state["last_expiry_warning_date"] = today_key
        return

    lines = ["<p><b>⚠️ The following emails will drop off your reply-needed list tomorrow:</b></p>"]
    for it in expiring[:10]:
        name = it.get("from_name") or it.get("from_email") or "Unknown"
        subj = (it.get("subject") or "(no subject)")[:120]
        received_short = (it.get("received") or "")[:10]
        lines.append(f"<p>• <b>{name}</b> — \"{subj}\" ({received_short})</p>")
    if len(expiring) > 10:
        lines.append(f"<p><i>... and {len(expiring) - 10} more</i></p>")
    lines.append("<p><i>To keep any of these, reply to them, save a draft in Outlook, or tell me which ones to keep following up on.</i></p>")
    html = "".join(lines)

    try:
        graph.send_html_message(chat_id, html)
        monitor_state["last_expiry_warning_date"] = today_key
        print(f"[EmailMonitor] Expiry warning sent: {len(expiring)} items")
    except Exception as e:
        print(f"[EmailMonitor] Expiry warning send failed: {e}")


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
    from src.ai import set_usage_context
    set_usage_context("email_monitor", data_dir.name)

    # Label every AI call in this poll as email_monitor + this user (was logged as
    # feature=unknown), and instrument the cycle below. Diagnostics only — no behavior change.
    from src.ai import set_usage_context
    set_usage_context("email_monitor", data_dir.name)

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
    seen_msg_ids = set(monitor_state.get("seen_msg_ids") or [])
    realtime_pushed_ids = set(monitor_state.get("realtime_pushed_ids") or [])

    # (Removed: the dead `pending_priority_followup` prune. That priority-followup-reminder feature
    # was retired when reply_needed became the single digest source (commit 14c3a9c, 2026-05-27) —
    # nothing has populated the list since, so this was a no-op on an always-empty list. Follow-up
    # dismissal now lives in followup_needed + the email_handled 'followup_dismissed' annotation.)

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
        _maybe_send_digest(graph, chat_id, data_dir, monitor_state, settings)
        _save_monitor_state(data_dir, monitor_state)
        return

    newest_ts = max(
        (m.get("receivedDateTime", "") for m in raw_emails),
        default=last_ts,
    )

    # Message-id dedup BEFORE any AI runs. The 'ge' filter re-fetches the boundary
    # email every cycle; without this it is re-screened forever (the burn). New emails
    # — including ones arriving at the same second as the boundary — are not in the
    # set, so they are still handled. This is what makes "no new email -> 0 AI" true.
    fresh = [m for m in raw_emails if (m.get("id") or "") not in seen_msg_ids]

    # Quiet cycles (no new email) log nothing — the DIAG below fires only when
    # there's actual work. Job liveness is tracked by the scheduler/ops dashboard.
    if fresh:
        # Build ignored_emails from CRM
        ignored_emails: set = set()
        try:
            crm_data = load_crm(data_dir)
            ignored_emails = {
                email for email, c in crm_data.get("contacts", {}).items()
                if c.get("ignore") or c.get("archived")
            }
        except Exception:
            pass

        from src.ai import AIClient
        ai = AIClient()

        # Screen (CLAUDE.md Principle 5)
        try:
            screened = screen_emails(
                messages=fresh,
                ai=ai,
                ignored_emails=ignored_emails,
                business_context=load_profile_context(data_dir),
                display_name=settings.get("display_name", "the executive"),
            )
            visible = [m for m in screened if not m.get("screened_out")]
        except Exception as e:
            print(f"[EmailMonitor] Screener error: {e}")
            visible = fresh

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
        new_actionable = False
        _pushed = 0   # DIAG

        for email_item in triaged:
            importance = email_item.get("_importance", "review")
            conv_id = email_item.get("conversationId") or email_item.get("id", "")
            processed_ids.add(conv_id)

            if importance == "skip":
                continue

            new_actionable = True
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
                    _pushed += 1
                    # Record so this email is never ALSO surfaced in the digest.
                    realtime_pushed_ids.add(email_item.get("id") or "")
                except Exception as e:
                    print(f"[EmailMonitor] Card send failed: {e}")
            else:
                # Non-priority (review) emails surface via reply_needed.json,
                # which the digest reads. No separate pending_digest queue.
                notified.append(summary)

        # Mark every email screened this cycle so the ge-boundary re-fetch never
        # re-screens them next cycle. Capped sliding window (same bound as conv ids).
        for m in fresh:
            _mid = m.get("id") or ""
            if _mid:
                seen_msg_ids.add(_mid)
        if len(seen_msg_ids) > _MAX_PROCESSED_IDS:
            seen_msg_ids = set(list(seen_msg_ids)[-_MAX_PROCESSED_IDS:])

        print(
            f"[EmailMonitor] DIAG uid={data_dir.name[:8]} last_ts={last_ts} "
            f"fetched={len(raw_emails)} fresh={len(fresh)} "
            f"screener_out={len(fresh) - len(visible)} "
            f"seen/noise_removed={len(visible) - len(filtered)} "
            f"triaged={len(triaged)}(crm={len(crm_classified)},ai={len(ai_triaged)}) "
            f"pushed={_pushed} newest_ts={newest_ts}"
        )

        if len(processed_ids) > _MAX_PROCESSED_IDS:
            processed_ids = set(list(processed_ids)[-_MAX_PROCESSED_IDS:])

        monitor_state["processed_conv_ids"] = list(processed_ids)
        monitor_state["seen_msg_ids"] = list(seen_msg_ids)
        if len(realtime_pushed_ids) > _MAX_PROCESSED_IDS:
            realtime_pushed_ids = set(list(realtime_pushed_ids)[-_MAX_PROCESSED_IDS:])
        monitor_state["realtime_pushed_ids"] = list(realtime_pushed_ids)
        monitor_state["last_notified_emails"] = notified[-20:]

        # Refresh reply_needed.json now so the digest + frontend reflect this batch.
        if new_actionable:
            # F4b: quantify how often the EXPENSIVE per-batch refresh fires (reply_needed.run is a
            # Graph + multi-Gemini section). Grep `[EmailMonitor] expensive-refresh` to decide whether
            # to make it incremental (add just the new emails) instead of a full re-run. Instrument
            # first, optimize later — behavior unchanged for now.
            print(f"[EmailMonitor] expensive-refresh uid={data_dir.name[:8]} "
                  f"reason=new_actionable triaged={len(triaged)}")
            try:
                from src.sections.reply_needed import run as run_reply_needed
                run_reply_needed(owner_graph, ai, data_dir, settings)
            except Exception as e:
                print(f"[EmailMonitor] reply_needed refresh failed: {e}")

            # F4a: extract commitments from the new mail into the live store in REAL TIME (was only
            # on the scheduled/manual run, so the commitments DB lagged new emails). commitments_extract
            # is incremental — it dedups via the processed_emails store, so only genuinely-new emails
            # hit the AI; gated on new_actionable so quiet cycles cost nothing. Labeled so the cost
            # shows as feature=commitments_extract, not email_monitor.
            # (Optimization for later if the re-screen cost matters: pass the already-screened `visible`
            #  emails in instead of letting commitments_extract re-fetch+re-screen them.)
            try:
                from src.ai import set_usage_context
                from src.sections.commitments_extract import run as run_commitments
                set_usage_context("commitments_extract", data_dir.name)
                try:
                    run_commitments(owner_graph, ai, data_dir, settings)
                finally:
                    set_usage_context("email_monitor", data_dir.name)   # restore for the rest of the poll
            except Exception as e:
                print(f"[EmailMonitor] commitments extract failed: {e}")

    monitor_state["last_checked_ts"] = newest_ts

    _maybe_send_digest(graph, chat_id, data_dir, monitor_state, settings)
    _maybe_send_expiry_warning(graph, chat_id, data_dir, monitor_state, settings)
    _save_monitor_state(data_dir, monitor_state)
