"""
meetings_today section — Event/On-demand.

Live Graph calendarView call for today (UTC midnight → tomorrow UTC midnight).
No caching, no AI. Each call returns the current view of the day.
"""
import hashlib
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output

_RESULT_ID = "meetings_today"

_DEFAULT_INSTRUCTION = """\
# Today's Meetings — User Preferences

Customise which meetings appear. Examples:

- "Only show the next meeting"
- "Skip 1:1s with my team"
- "Hide focus blocks and lunch"
- "Skip anything titled 'sync' or 'standup'"
"""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / f"{_RESULT_ID}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _format_time(iso_str: str) -> str:
    """Convert ISO datetime to HH:MM in local-ish format (UTC for now)."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return iso_str[11:16] if len(iso_str) >= 16 else iso_str


def _build_item(event: dict) -> dict:
    subject = event.get("subject") or "(no subject)"
    start = (event.get("start") or {}).get("dateTime") or ""
    end = (event.get("end") or {}).get("dateTime") or ""
    location = (event.get("location") or {}).get("displayName", "")
    attendees = [
        ((a.get("emailAddress") or {}).get("name") or
         (a.get("emailAddress") or {}).get("address") or "")
        for a in event.get("attendees", [])
    ]
    attendees = [a for a in attendees if a]
    body = (event.get("bodyPreview") or "").strip()
    is_all_day = bool(event.get("isAllDay"))

    key = (event.get("id") or "") + "|" + subject
    return {
        "id":          hashlib.sha1(key.encode()).hexdigest()[:16],
        "subject":     subject,
        "start":       start,
        "end":         end,
        "start_time":  _format_time(start),
        "end_time":    _format_time(end),
        "is_all_day":  is_all_day,
        "location":    location,
        "attendees":   attendees[:10],
        "attendee_count": len(attendees),
        "body_preview": body[:300],
    }


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
        print(f"[meetings_today] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    today = date.today()
    start_utc = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    _p(f"Fetching calendar for {today.isoformat()}")

    try:
        events = graph.get_calendar_view(
            start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            top=50,
        )
    except Exception as e:
        _p(f"Calendar fetch failed: {e}")
        events = []

    events.sort(key=lambda e: (e.get("start") or {}).get("dateTime") or "")
    items = [_build_item(e) for e in events]

    _p(f"{len(items)} meeting(s) before user-preference review")

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
        "date":     today.isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(items)} meeting(s) today after review")
    return result
