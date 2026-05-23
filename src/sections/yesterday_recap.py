"""
yesterday_recap section — Scheduled (morning push).

Lightweight snapshot of yesterday's activity:
  - Yesterday's inbound emails (top by priority from reply_needed if available,
    else from raw Graph inbox metadata)
  - Yesterday's outbound emails (from Graph sent items)
  - Yesterday's meetings (from Graph calendarView)
  - Yesterday's new commitments (from commitments_extract.json)

No AI. Just aggregation + counts + a few top items per category.
"""
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output

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


def _format_time(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return iso_str[11:16] if len(iso_str) >= 16 else iso_str


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
    yesterday = date.today() - timedelta(days=1)
    y_str = yesterday.isoformat()

    start_utc = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    # ── Inbound emails ──────────────────────────────────────
    _p("Fetching yesterday's inbox metadata...")
    try:
        inbox = graph.get_inbox_metadata_since(days=2, max_results=500)
    except Exception as e:
        _p(f"Inbox fetch failed: {e}")
        inbox = []
    inbound_yesterday = [
        m for m in inbox
        if (m.get("receivedDateTime") or "")[:10] == y_str
    ]

    # ── Outbound emails ─────────────────────────────────────
    _p("Fetching yesterday's sent items...")
    try:
        sent = graph.get_sent_messages_since(days=2, max_results=500)
    except Exception as e:
        _p(f"Sent fetch failed: {e}")
        sent = []
    outbound_yesterday = [
        m for m in sent
        if (m.get("sentDateTime") or "")[:10] == y_str
    ]

    # ── Meetings ────────────────────────────────────────────
    _p("Fetching yesterday's calendar...")
    try:
        events = graph.get_calendar_view(
            start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            top=50,
        )
    except Exception as e:
        _p(f"Calendar fetch failed: {e}")
        events = []

    # ── Commitments extracted from yesterday's emails ───────
    com_path = data_dir / "results" / "commitments_extract.json"
    com_items = _read_json(com_path).get("items", [])
    commitments_yesterday = [
        c for c in com_items
        if (c.get("received") or "")[:10] == y_str
    ]

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
            "time":    _format_time(m.get("receivedDateTime") or ""),
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
            "time":    _format_time(m.get("sentDateTime") or ""),
        })

    for ev in sorted(events,
                     key=lambda e: (e.get("start") or {}).get("dateTime") or ""):
        items.append({
            "type":      "meeting",
            "subject":   ev.get("subject") or "(no subject)",
            "start":     _format_time((ev.get("start") or {}).get("dateTime") or ""),
            "end":       _format_time((ev.get("end") or {}).get("dateTime") or ""),
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
    date_str = datetime.now().strftime("%A, %B %d, %Y")
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
