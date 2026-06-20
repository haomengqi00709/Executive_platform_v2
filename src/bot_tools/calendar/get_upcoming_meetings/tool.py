import json
from datetime import datetime, timedelta, timezone

IS_ACTION = False


def build(ctx):
    def get_upcoming_meetings(hours_ahead: int = 24) -> str:
        from src.bot import _with_indices
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            now    = datetime.now(timezone.utc)
            end_dt = now + timedelta(hours=hours_ahead)
            events = owner_graph.get_calendar_view(
                start_dt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_dt=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                top=20,
            )
            result = []
            for e in events:
                attendees = [
                    a.get("emailAddress", {}).get("address", "")
                    for a in (e.get("attendees") or [])
                ]
                result.append({
                    "event_id":  e.get("id", ""),
                    "title":     e.get("subject", ""),
                    "start":     (e.get("start") or {}).get("dateTime", "")[:16],
                    "end":       (e.get("end") or {}).get("dateTime", "")[:16],
                    "attendees": attendees,
                    "location":  e.get("location", {}).get("displayName", ""),
                })
            result = _with_indices(result)
            print(f"[Bot] get_upcoming_meetings({hours_ahead}h) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_upcoming_meetings
