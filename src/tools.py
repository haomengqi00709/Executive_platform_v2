"""
Atomic tools for the Agent Loop.
Each function = one capability the AI can invoke.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.modules.wiki import load_index, load_meeting, get_meeting_action_items


def get_upcoming_meetings(graph: GraphClient, hours_ahead: int = 24) -> list:
    """Get calendar meetings starting within the next N hours (default: rest of today)."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours_ahead)
    events = graph.get_calendar_view(
        start_dt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        top=10,
    )
    result = []
    for e in events:
        attendees = [
            a["emailAddress"]["address"]
            for a in e.get("attendees", [])
            if a.get("emailAddress", {}).get("address")
        ]
        result.append({
            "id":           e.get("id", ""),
            "title":        e.get("subject", "(no subject)"),
            "start":        e.get("start", {}).get("dateTime", "")[:16].replace("T", " "),
            "end":          e.get("end", {}).get("dateTime", "")[:16].replace("T", " "),
            "location":     e.get("location", {}).get("displayName", ""),
            "attendees":    attendees,
            "body_preview": e.get("bodyPreview", "")[:200],
        })
    return result


def get_contact_history(data_dir: Path, email: str) -> dict:
    """Get CRM info and meeting history with a specific contact."""
    from src.modules.crm import load_crm
    email = email.lower().strip()

    crm = load_crm(data_dir)
    contact = crm.get("contacts", {}).get(email, {})

    wiki_dir = Path(data_dir) / "wiki"
    index = load_index(wiki_dir)
    meetings_found = []
    for mid in index.get("meetings", {}):
        full = load_meeting(wiki_dir, mid)
        if full and email in [e.lower() for e in full.get("attendee_emails", [])]:
            meetings_found.append({
                "title":        full.get("title", ""),
                "date":         full.get("date", ""),
                "summary":      full.get("summary", "")[:200],
                "action_items": full.get("action_items", [])[:3],
            })
    meetings_found.sort(key=lambda x: x.get("date", ""), reverse=True)

    return {
        "email":           email,
        "contact":         contact,
        "meeting_count":   len(meetings_found),
        "recent_meetings": meetings_found[:3],
    }


def get_open_action_items(data_dir: Path, attendee_email: str = None) -> list:
    """Get unresolved action items from recent meetings, optionally filtered by owner."""
    wiki_dir = Path(data_dir) / "wiki"
    items = get_meeting_action_items(wiki_dir, days=30)
    if attendee_email:
        hint = attendee_email.lower().split("@")[0]
        items = [
            i for i in items
            if hint in (i.get("owner") or "").lower()
            or attendee_email.lower() in (i.get("owner") or "").lower()
        ]
    return [i for i in items if not i.get("completed")][:10]


def get_past_meetings(graph: GraphClient, days_back: int = 2, top: int = 20) -> list:
    """Get calendar meetings that occurred in the past N days."""
    now        = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=days_back)).date()
    since      = datetime(since_date.year, since_date.month, since_date.day,
                          0, 0, 0, tzinfo=timezone.utc)
    events = graph.get_calendar_view(
        start_dt=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        top=top,
    )
    results = []
    for e in events:
        attendees = [
            a["emailAddress"].get("name") or a["emailAddress"].get("address", "")
            for a in e.get("attendees", [])
            if a.get("emailAddress", {}).get("address")
        ]
        results.append({
            "title":     e.get("subject", "(no subject)"),
            "start":     e.get("start", {}).get("dateTime", "")[:16].replace("T", " "),
            "end":       e.get("end",   {}).get("dateTime", "")[:16].replace("T", " "),
            "attendees": attendees[:6],
            "location":  e.get("location", {}).get("displayName", ""),
        })
    return results


def get_recent_emails(graph: GraphClient, hours_back: int = 24, top: int = 20) -> list:
    """Get emails received in the last N hours from the inbox."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    msgs = graph.get_messages(
        top=top,
        filter=f"receivedDateTime ge {since}",
        orderby="receivedDateTime desc",
    )
    results = []
    for m in msgs:
        sender = m.get("from", {}).get("emailAddress", {})
        results.append({
            "subject":  m.get("subject", "(no subject)"),
            "from":     sender.get("name", sender.get("address", "")),
            "received": m.get("receivedDateTime", "")[:16].replace("T", " "),
            "preview":  m.get("bodyPreview", "")[:200],
            "is_read":  m.get("isRead", True),
            "importance": m.get("importance", "normal"),
        })
    return results


def get_email_commitments(results_dir: Path, section: str) -> list:
    """
    Read cached M01 email action items from the last briefing run.
    section must be one of:
      'reply_needed'   — emails received where the user has not yet replied
      'followup_needed'— emails the user sent that have received no response
      'commitments'    — upcoming commitments extracted from email (due in next 7 days)
    Returns a list of items; each has subject, days_waiting (or due_date), is_urgent, project_name.
    """
    try:
        path = Path(results_dir) / "m01_latest.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        oc   = data.get("open_commitments") or {}
        return (oc.get(section) or [])[:15]
    except Exception:
        return []


def search_web(query: str, user_context: str = "") -> str:
    """
    Search Google for any real-time information using Gemini Google Search grounding.
    query: a natural language search instruction, e.g.
      "Recent news (last 14 days) about Acme Corp and equipment manufacturing industry"
      "Latest AI consulting market trends and competitor moves"
      "What is the current regulatory status of water utilities in Alberta?"
    user_context: optional background about the user to focus results (injected automatically).
    Returns a formatted text response with sources.
    """
    import os
    from google import genai
    from google.genai import types

    today   = datetime.now().strftime("%A, %B %d, %Y")
    preamble = f"Today is {today}.\n"
    if user_context:
        preamble += f"User context: {user_context}\n"

    try:
        gc     = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        result = gc.models.generate_content(
            model   = "gemini-2.5-flash",
            contents= preamble + "\n" + query,
            config  = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return result.text or "No results found."
    except Exception as e:
        return f"Search failed: {e}"


def read_user_data(data_dir: Path, data_type: str, filter: str = "") -> dict:
    """
    Read the user's local data files. The AI decides what to read based on the question.

    data_type options:
      'crm'       — CRM contacts grouped by company.
                    filter: priority level ('critical', 'high', 'medium', 'low') or empty for all.
      'companies' — Company Profiles database (Market Segments classifications).
                    filter: industry keyword or customer_type or priority to narrow results.
      'briefing'  — Latest M01 briefing results.
                    filter: 'reply_needed' | 'followup_needed' | 'commitments' for a specific section.
      'context'   — Profile context documents (business_profile, writing_style, market_segments, etc.).
                    filter: document slug to get full content of one doc.
      'settings'  — Current user settings (display_name, timezone, report_email, etc.).
    """
    try:
        data_dir = Path(data_dir)

        if data_type == "crm":
            path = data_dir / "crm.json"
            if not path.exists():
                return {"error": "CRM not found — run a CRM scan first"}
            crm_data = json.loads(path.read_text())
            contacts_dict = crm_data.get("contacts", {})
            if filter and "@" in filter:
                contact = contacts_dict.get(filter.lower())
                if contact:
                    return {"contact": contact}
                return {"error": f"Contact {filter} not found in CRM"}
            contacts = list(contacts_dict.values())
            if filter:
                contacts = [c for c in contacts if (c.get("priority") or "").lower() == filter.lower()]
            seen: dict = {}
            for c in contacts:
                comp = (c.get("company") or "").strip()
                if comp and comp not in seen:
                    seen[comp] = {"name": comp, "priority": c.get("priority", ""),
                                  "industry": c.get("industry", ""), "status": c.get("status", "")}
            return {"companies": list(seen.values())[:40], "total_contacts": len(contacts)}

        elif data_type == "companies":
            path = data_dir / "companies.json"
            if not path.exists():
                return {"error": "Company profiles not found — upload files or run an email scan first"}
            companies = list(json.loads(path.read_text()).get("companies", {}).values())
            if filter:
                fl = filter.lower()
                companies = [c for c in companies if
                             fl in (c.get("priority") or "").lower() or
                             fl in (c.get("industry") or "").lower() or
                             fl in (c.get("customer_type") or "").lower() or
                             fl in (c.get("name") or "").lower()]
            return {"companies": companies[:40]}

        elif data_type == "briefing":
            path = data_dir / "results" / "m01_latest.json"
            if not path.exists():
                return {"error": "No briefing results yet — run Morning Briefing (M01) first"}
            data = json.loads(path.read_text())
            oc   = data.get("open_commitments") or {}
            if filter and filter in ("reply_needed", "followup_needed", "commitments"):
                return {filter: (oc.get(filter) or [])[:15]}
            return {
                "generated_at":    data.get("generated_at", ""),
                "briefing_summary": data.get("briefing", "")[:600],
                "reply_needed":    (oc.get("reply_needed")    or [])[:10],
                "followup_needed": (oc.get("followup_needed") or [])[:10],
                "commitments":     (oc.get("commitments")     or [])[:10],
            }

        elif data_type == "context":
            path = data_dir / "context.json"
            if not path.exists():
                return {"error": "Context docs not found"}
            docs = json.loads(path.read_text()).get("documents", {})
            if filter and filter in docs:
                return {filter: docs[filter].get("content", "")[:3000]}
            return {slug: (doc.get("content", "")[:300] + "…") for slug, doc in docs.items() if doc.get("content")}

        elif data_type == "settings":
            path = data_dir / "settings.json"
            if not path.exists():
                return {"error": "Settings not found"}
            return json.loads(path.read_text())

        else:
            return {"error": f"Unknown data_type '{data_type}'. Valid: crm, companies, briefing, context, settings"}

    except Exception as e:
        return {"error": str(e)}


def set_market_intel_focus(data_dir: Path, industries: str) -> dict:
    """
    Persistently update which industries the daily Market Intelligence section tracks.
    industries: comma-separated list, e.g. "equipment manufacturing, water utilities"
                Pass an empty string to reset to all industries (default behaviour).
    Writes market_intel_focus to settings.json — takes effect on the next M01 run.
    """
    try:
        path     = Path(data_dir) / "settings.json"
        settings = json.loads(path.read_text()) if path.exists() else {}
        settings["market_intel_focus"] = industries.strip()
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))
        if industries.strip():
            return {"ok": True, "message": f"Market Intelligence will now focus on: {industries.strip()}. Takes effect on the next morning briefing run."}
        else:
            return {"ok": True, "message": "Market Intelligence reset to all industries from your Company Profiles."}
    except Exception as e:
        return {"error": str(e)}


def send_teams_message(content: str, webhook_url: str) -> bool:
    """Send a plain message to the Teams channel."""
    from src.notify import send_teams
    return send_teams("CEO Assistant", content, webhook_url=webhook_url)


def send_meeting_brief_card(
    meeting_title: str,
    meeting_time: str,
    attendees: str,
    background: str,
    open_items: str,
    suggested_agenda: str,
    webhook_url: str,
) -> bool:
    """Send a formatted pre-meeting preparation card to Teams."""
    from src.notify import _post, _card

    body = [
        {"type": "TextBlock", "text": "📋  Meeting Prep Brief", "weight": "Bolder", "size": "Large"},
        {"type": "TextBlock", "text": meeting_title, "weight": "Bolder", "size": "Medium", "spacing": "None"},
        {"type": "TextBlock", "text": f"🕐 {meeting_time}", "size": "Small", "color": "Accent", "spacing": "None"},
    ]
    if attendees:
        body.append({"type": "TextBlock", "text": f"👥 {attendees}", "size": "Small", "spacing": "None", "wrap": True})
    if background:
        body.append({"type": "TextBlock", "text": "📌 Background", "weight": "Bolder", "size": "Small", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": background, "wrap": True, "size": "Small", "spacing": "None"})
    if open_items:
        body.append({"type": "TextBlock", "text": "⚠️ Open Items", "weight": "Bolder", "size": "Small", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": open_items, "wrap": True, "size": "Small", "spacing": "None"})
    if suggested_agenda:
        body.append({"type": "TextBlock", "text": "💡 Suggested Agenda", "weight": "Bolder", "size": "Small", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": suggested_agenda, "wrap": True, "size": "Small", "spacing": "None"})

    return _post(_card(body), webhook_url=webhook_url)
