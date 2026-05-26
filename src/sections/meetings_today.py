"""
meetings_today section — Event/On-demand.

Live Graph calendarView call for today (UTC midnight → tomorrow UTC midnight).
No caching, no AI. Each call returns the current view of the day.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.tz import (
    get_user_tz, now_local, today_local_str, local_day_window_utc, format_local_time,
)

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


def _build_item(event: dict, tz: ZoneInfo) -> dict:
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
        "start_time":  format_local_time(start, tz),
        "end_time":    format_local_time(end, tz),
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
    tz = get_user_tz(data_dir)
    today_str = today_local_str(data_dir)
    start_utc_iso, end_utc_iso = local_day_window_utc(data_dir, 0)

    _p(f"Fetching calendar for {today_str} ({tz.key})")

    try:
        events = graph.get_calendar_view(start_utc_iso, end_utc_iso, top=50)
    except Exception as e:
        _p(f"Calendar fetch failed: {e}")
        events = []

    events.sort(key=lambda e: (e.get("start") or {}).get("dateTime") or "")
    items = [_build_item(e, tz) for e in events]

    _p(f"{len(items)} meeting(s) before user-preference review")

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
        "date":     today_str,
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(items)} meeting(s) today after review")
    return result
