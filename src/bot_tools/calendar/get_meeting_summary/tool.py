import json
from datetime import datetime, timedelta, timezone

IS_ACTION = False


def build(ctx):
    def get_meeting_summary(event_id_or_subject: str) -> str:
        from src.modules.subject_match import normalize_subject
        from src.modules.wiki import load_index, load_meeting
        data_dir = ctx.data_dir
        wiki_dir = ctx.wiki_dir
        owner_graph = ctx.owner_graph
        if not data_dir:
            return "No data directory available."
        q = (event_id_or_subject or "").strip()
        if not q:
            return "Please provide an event id or subject keyword."
        q_low = q.lower()
        q_norm = normalize_subject(q)

        # (1) Wiki search — exact meeting_id or title substring
        if wiki_dir and wiki_dir.exists():
            try:
                idx = load_index(wiki_dir)
                meetings = idx.get("meetings", {}) or {}
                # Exact meeting_id match
                if q in meetings:
                    full = load_meeting(wiki_dir, q)
                    if full:
                        print(f"[Bot] get_meeting_summary({q}) → wiki exact id")
                        return json.dumps({
                            "source":      "wiki",
                            "meeting_id":  q,
                            "title":       full.get("title", ""),
                            "date":        full.get("date", ""),
                            "summary":     full.get("summary", ""),
                            "decisions":   full.get("decisions", []),
                            "action_items": full.get("action_items", []),
                            "attendee_emails": full.get("attendee_emails", []),
                        }, ensure_ascii=False)
                # Title substring match
                for mid, meta in meetings.items():
                    title = (meta.get("title") or "")
                    title_low = title.lower()
                    if q_low in title_low or (q_norm and q_norm in normalize_subject(title)):
                        full = load_meeting(wiki_dir, mid)
                        if full:
                            print(f"[Bot] get_meeting_summary({q}) → wiki title match {mid}")
                            return json.dumps({
                                "source":      "wiki",
                                "meeting_id":  mid,
                                "title":       full.get("title", ""),
                                "date":        full.get("date", ""),
                                "summary":     full.get("summary", ""),
                                "decisions":   full.get("decisions", []),
                                "action_items": full.get("action_items", []),
                                "attendee_emails": full.get("attendee_emails", []),
                            }, ensure_ascii=False)
            except Exception as e:
                print(f"[Bot] wiki lookup failed: {e}")

        # (2) Calendar fallback — scheduled but unrecorded
        if owner_graph is None:
            return json.dumps({
                "source":  "none",
                "message": f"No wiki meeting matches '{q}', and calendar is not available.",
            }, ensure_ascii=False)
        try:
            now = datetime.now(timezone.utc)
            start = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
            events = owner_graph.get_calendar_view(start, end, top=100)
            # Exact event.id match
            evt = next((e for e in events if e.get("id") == q), None)
            if evt is None:
                # Subject substring match — most recent first
                events_sorted = sorted(
                    events,
                    key=lambda e: (e.get("start") or {}).get("dateTime", ""),
                    reverse=True,
                )
                for e in events_sorted:
                    subj = (e.get("subject") or "")
                    if q_low in subj.lower() or (q_norm and q_norm in normalize_subject(subj)):
                        evt = e
                        break
            if evt:
                print(f"[Bot] get_meeting_summary({q}) → calendar match")
                return json.dumps({
                    "source":   "calendar",
                    "event_id": evt.get("id", ""),
                    "subject":  evt.get("subject", ""),
                    "start":    (evt.get("start") or {}).get("dateTime", ""),
                    "end":      (evt.get("end") or {}).get("dateTime", ""),
                    "attendees": [
                        ((a.get("emailAddress") or {}).get("address") or "")
                        for a in (evt.get("attendees") or [])
                    ],
                    "note": "Meeting has no summary yet — scheduled but not recorded.",
                }, ensure_ascii=False)
        except Exception as e:
            print(f"[Bot] calendar fallback failed: {e}")

        return json.dumps({
            "source":  "none",
            "message": f"No wiki record or calendar event matches '{q}'.",
        }, ensure_ascii=False)
    return get_meeting_summary
