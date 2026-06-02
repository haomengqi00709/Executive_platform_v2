"""
yesterday_recap section — Scheduled (morning push).

Lightweight snapshot of yesterday's activity:
  - Yesterday's inbound emails (Graph inbox metadata → screen_emails, Principle 5)
  - Yesterday's outbound emails (from Graph sent items)
  - Yesterday's meetings (from Graph calendarView)
  - Yesterday's new commitments (from commitments_extract.json)

Inbound mail is screened (screen_emails) and the assembled list gets a final
user-preference pass (validate_output); sent/meetings/commitments are aggregation.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.screener import screen_emails
from src.modules.crm import load_crm
from src.modules.profile import load_profile_context
from src.modules.tz import (
    get_user_tz, now_local, local_day_window_utc, format_local_time,
)

_RESULT_ID = "yesterday_recap"

_DEFAULT_INSTRUCTION = """\
# Yesterday's Recap — User Preferences

Customise which items appear in the recap. Examples:

- "Skip internal email chit-chat — only show external contacts"
- "Drop newsletters and notifications"
- "Only show meetings, hide emails"
"""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / f"{_RESULT_ID}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict,
    progress=None,
    force_refresh: bool = False,
) -> dict:
    def _p(msg: str):
        if progress:
            progress(msg)
        print(f"[yesterday_recap] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    tz = get_user_tz(data_dir)
    # Local-yesterday window expressed in UTC ISO strings — used both for
    # the Graph calendar query and for filtering already-fetched inbox/sent
    # metadata by their UTC receivedDateTime.
    start_utc_iso, end_utc_iso = local_day_window_utc(data_dir, -1)
    y_str = (now_local(data_dir).date() - timedelta(days=1)).isoformat()

    def _in_yesterday_window(iso: str) -> bool:
        return bool(iso) and start_utc_iso <= iso < end_utc_iso

    # ── Inbound emails (screened — Principle 5) ─────────────
    _p("Fetching yesterday's inbox metadata...")
    try:
        inbox = graph.get_inbox_metadata_since(days=2, max_results=500)
    except Exception as e:
        _p(f"Inbox fetch failed: {e}")
        inbox = []
    inbound_yesterday = [m for m in inbox if _in_yesterday_window(m.get("receivedDateTime") or "")]

    # Principle 5: anything we surface to the user must pass the screener first.
    # Filter to yesterday before screening so we only screen that day's mail.
    if inbound_yesterday:
        crm_contacts = load_crm(data_dir).get("contacts", {})
        ignored_emails = {
            e for e, c in crm_contacts.items()
            if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore"
        }
        _p(f"Screening {len(inbound_yesterday)} inbound email(s)...")
        screened = screen_emails(
            messages=inbound_yesterday,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=load_profile_context(data_dir),
            display_name=(settings or {}).get("display_name", "the executive"),
            progress=progress,
        )
        inbound_yesterday = [m for m in screened if not m.get("screened_out")]

    # ── Outbound emails ─────────────────────────────────────
    _p("Fetching yesterday's sent items...")
    try:
        sent = graph.get_sent_messages_since(days=2, max_results=500)
    except Exception as e:
        _p(f"Sent fetch failed: {e}")
        sent = []
    outbound_yesterday = [m for m in sent if _in_yesterday_window(m.get("sentDateTime") or "")]

    # ── Meetings ────────────────────────────────────────────
    _p("Fetching yesterday's calendar...")
    try:
        events = graph.get_calendar_view(start_utc_iso, end_utc_iso, top=50)
    except Exception as e:
        _p(f"Calendar fetch failed: {e}")
        events = []

    # ── Commitments extracted from yesterday's emails ───────
    com_path = data_dir / "results" / "commitments_extract.json"
    com_items = _read_json(com_path).get("items", [])
    commitments_yesterday = [c for c in com_items if _in_yesterday_window(c.get("received") or "")]

    # ── Build items list ────────────────────────────────────
    items: list[dict] = []

    for m in sorted(inbound_yesterday,
                    key=lambda x: x.get("receivedDateTime") or "",
                    reverse=True)[:5]:
        ea = (m.get("from") or {}).get("emailAddress") or {}
        items.append({
            "type":    "inbound_email",
            "subject": (m.get("subject") or "(no subject)")[:120],
            "from":    ea.get("name") or ea.get("address") or "—",
            "time":    format_local_time(m.get("receivedDateTime") or "", tz),
        })

    for m in sorted(outbound_yesterday,
                    key=lambda x: x.get("sentDateTime") or "",
                    reverse=True)[:5]:
        to_list = m.get("toRecipients") or []
        to_addr = ((to_list[0] if to_list else {}).get("emailAddress") or {})
        items.append({
            "type":    "outbound_email",
            "subject": (m.get("subject") or "(no subject)")[:120],
            "to":      to_addr.get("name") or to_addr.get("address") or "—",
            "time":    format_local_time(m.get("sentDateTime") or "", tz),
        })

    for ev in sorted(events,
                     key=lambda e: (e.get("start") or {}).get("dateTime") or ""):
        items.append({
            "type":      "meeting",
            "subject":   ev.get("subject") or "(no subject)",
            "start":     format_local_time((ev.get("start") or {}).get("dateTime") or "", tz),
            "end":       format_local_time((ev.get("end") or {}).get("dateTime") or "", tz),
            "attendees": [
                ((a.get("emailAddress") or {}).get("name") or
                 (a.get("emailAddress") or {}).get("address") or "")
                for a in ev.get("attendees", [])
            ][:5],
        })

    for c in commitments_yesterday[:8]:
        items.append({
            "type":         "commitment",
            "commit_kind":  c.get("type", "my_commitment"),
            "description":  (c.get("description") or "")[:160],
            "contact_name": c.get("contact_name") or c.get("contact_email") or "",
            "due_date":     c.get("due_date") or "",
        })

    stats = {
        "inbound_count":     len(inbound_yesterday),
        "outbound_count":    len(outbound_yesterday),
        "meetings_count":    len(events),
        "commitments_count": len(commitments_yesterday),
    }

    _p(f"{len(items)} item(s) before user-preference review")

    user_instruction = _load_user_instruction(data_dir)
    display_name = (settings or {}).get("display_name") or "the executive"
    date_str = now_local(data_dir).strftime("%A, %B %d, %Y")
    items = validate_output(
        items, ai,
        section_id=_RESULT_ID,
        user_instruction=user_instruction,
        display_name=display_name,
        date_str=date_str,
    )

    result = {
        "id":       _RESULT_ID,
        "status":   "fresh",
        "last_run": now.isoformat(),
        "date":     y_str,
        "stats":    stats,
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {stats['inbound_count']} in / {stats['outbound_count']} out / "
       f"{stats['meetings_count']} meeting(s) / {stats['commitments_count']} commitment(s)")
    return result
