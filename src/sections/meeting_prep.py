"""
meeting_prep section — Event/Triggered (driven by upcoming calendar).

Polled by the scheduler every 5 minutes for users with meeting.prep_enabled=true
in schedules.json. For each upcoming meeting starting within
[now, now + prep_minutes_before + 5min window], if we haven't sent prep yet,
builds rich pre-meeting context and pushes to Teams.

Prep content per meeting:
  - Meeting title + time + attendee list
  - Per-attendee CRM context (company, role, status, last_contact, summary)
  - Related active projects
  - Open action items from previous meetings with same attendees
  - AI-written 2-sentence "remember Y about X" hint
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.tz import get_user_tz, format_local_time


_RESULT_ID = "meeting_prep"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _build_attendee_context(email: str, crm: dict, contacts_by_email: dict) -> dict:
    c = contacts_by_email.get(email.lower()) or {}
    return {
        "email":        email,
        "name":         c.get("name") or email,
        "company":      c.get("company", ""),
        "role":         c.get("role", ""),
        "status":       c.get("status", ""),
        "last_contact": c.get("last_contact", ""),
        "summary":      (c.get("summary") or "")[:300],
        "writing_style": (c.get("writing_style") or "")[:200],
    }


def _related_projects(attendee_emails: set, projects_data: dict) -> list[dict]:
    """Find active projects with any of the attendees as participants."""
    out = []
    active_states = {"ongoing", "needs_attention", "paused", "early_stage"}
    for p in projects_data.get("projects", {}).values():
        if p.get("ignore") or p.get("archived"):
            continue
        if p.get("status") not in active_states:
            continue
        participants = {e.lower() for e in (p.get("participants") or [])}
        overlap = participants & attendee_emails
        if overlap:
            out.append({
                "id":           p.get("id", ""),
                "name":         p.get("name", ""),
                "status":       p.get("status", ""),
                "momentum":     p.get("momentum", ""),
                "summary":      (p.get("summary") or "")[:200],
                "next_action":  (p.get("next_action") or "")[:200],
                "matched_attendees": sorted(overlap),
            })
    return out


def _open_actions_for_attendees(attendee_emails: set, action_items: list[dict]) -> list[dict]:
    """From meeting_action_items results, find items where owner is one of the attendees
    OR meeting title involved them. Best-effort string match."""
    out = []
    attendee_names_lower = {e.split("@")[0].lower() for e in attendee_emails}
    for it in action_items[:80]:
        owner = (it.get("owner") or "").lower()
        # Match owner name against attendee email prefix
        if any(n in owner for n in attendee_names_lower if n):
            out.append({
                "action":      (it.get("action") or "")[:200],
                "owner":       it.get("owner", ""),
                "due_date":    it.get("due_date"),
                "meeting":     it.get("meeting_title", ""),
                "meeting_date": it.get("meeting_date", ""),
            })
    return out[:8]


_DEFAULT_INSTRUCTION = """\
# Meeting Prep — User Preferences

Customise what the pre-meeting reminder should emphasise. Examples:

- "Always remind me of any outstanding action items I owe the attendees"
- "Lead with the deal value if there's a pipeline opportunity"
- "Skip prep for internal 1:1s with my direct reports"
- "Mention what their company has been in the news for recently"
"""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / f"{_RESULT_ID}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _ai_remember_hint(meeting: dict, attendee_ctx: list[dict], projects: list[dict],
                     open_actions: list[dict], ai: AIClient, display_name: str,
                     user_instruction: str = "") -> str:
    """Ask AI for a 2-sentence remember-this hint."""
    lines = [
        f"You are about to draft a pre-meeting reminder for {display_name}.",
        f"Meeting: {meeting.get('subject', '(untitled)')}",
        f"Starts: {meeting.get('start_local', meeting.get('start', ''))}",
        f"Attendees:",
    ]
    for a in attendee_ctx[:6]:
        lines.append(
            f"  - {a['name']} ({a['email']}) — {a.get('role', '')} at {a.get('company', '')}, "
            f"status={a.get('status', '')}, last_contact={a.get('last_contact', '—')}"
        )
        if a.get("summary"):
            lines.append(f"      summary: {a['summary'][:150]}")
    if projects:
        lines.append("Related active projects:")
        for p in projects:
            lines.append(f"  - {p['name']} ({p['status']}/{p['momentum']}) — {p['summary'][:120]}")
    if open_actions:
        lines.append("Open action items involving attendees:")
        for a in open_actions[:5]:
            due = f" (due {a['due_date']})" if a.get("due_date") else ""
            lines.append(f"  - {a['owner']}: {a['action'][:140]}{due}")
    lines.append("")
    lines.append(
        "Write a single paragraph (2-3 sentences) starting with \"Remember:\" "
        "that names the most important context and the one outstanding thing the executive "
        "should bring up. Use real names. No filler."
    )
    if user_instruction:
        lines.append("")
        lines.append("USER PREFERENCES (override anything above if contradicted):")
        lines.append(user_instruction)
    try:
        text = ai.generate("\n".join(lines)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return text[:600]
    except Exception as e:
        return f"(AI hint unavailable: {e})"


def _format_for_teams(prep: dict) -> str:
    lines = [f"🕐 **Pre-meeting prep** — {prep['subject']} at {prep['start_local']}"]
    if prep.get("location"):
        lines.append(f"📍 {prep['location']}")
    if prep.get("attendees"):
        lines.append("")
        lines.append("**Attendees:**")
        for a in prep["attendees"][:6]:
            line = f"  • {a['name']}"
            tags = []
            if a.get("company"): tags.append(a["company"])
            if a.get("role"): tags.append(a["role"])
            if a.get("status") and a["status"] != "other": tags.append(a["status"])
            if tags:
                line += f" — {' · '.join(tags)}"
            if a.get("last_contact"):
                line += f"  (last contact {a['last_contact']})"
            lines.append(line)
    if prep.get("related_projects"):
        lines.append("")
        lines.append("**Related projects:**")
        for p in prep["related_projects"][:4]:
            lines.append(f"  • **{p['name']}** ({p['status']}/{p['momentum']}) — {p['summary']}")
            if p.get("next_action"):
                lines.append(f"    → {p['next_action']}")
    if prep.get("open_actions"):
        lines.append("")
        lines.append("**Open action items:**")
        for a in prep["open_actions"][:5]:
            due = f"  (due {a['due_date']})" if a.get("due_date") else ""
            lines.append(f"  • {a['owner']}: {a['action']}{due}")
    if prep.get("remember"):
        lines.append("")
        lines.append(prep["remember"])
    return "\n".join(lines)


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict,
    progress=None,
    force_refresh: bool = False,
) -> dict:
    """Scan upcoming meetings and produce prep items for any not yet prepped.
    Caller (poller or section runner) is responsible for actually pushing
    to Teams — we return the items list and let the caller decide.
    """
    def _p(msg: str):
        if progress:
            progress(msg)
        print(f"[meeting_prep] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    tz = get_user_tz(data_dir)
    user_instruction = _load_user_instruction(data_dir)

    # Load schedule config for prep_minutes_before
    from src.modules.schedules import load_schedules
    sched = load_schedules(data_dir)
    meeting_cfg = sched.get("meeting", {})
    prep_enabled = meeting_cfg.get("prep_enabled", False)
    prep_minutes = int(meeting_cfg.get("prep_minutes_before", 30))

    if not prep_enabled and not force_refresh:
        return {
            "id":       _RESULT_ID,
            "status":   "not_run",
            "last_run": now.isoformat(),
            "items":    [],
            "count":    0,
            "empty":    True,
            "empty_reason": "prep_disabled",
        }

    # Window: now → now + prep_minutes + 10 min buffer
    window_end = now + timedelta(minutes=prep_minutes + 10)
    _p(f"Scanning calendar for meetings starting in next {prep_minutes + 10} min")

    try:
        events = graph.get_calendar_view(
            now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            top=20,
        )
    except Exception as e:
        _p(f"Calendar fetch failed: {e}")
        events = []

    if not events:
        result = {
            "id":       _RESULT_ID,
            "status":   "fresh",
            "last_run": now.isoformat(),
            "items":    [],
            "count":    0,
            "empty":    True,
        }
        _save_json(results_path, result)
        return result

    # Load seen + context sources
    seen_path = data_dir / "meeting_prep_seen.json"
    seen = _load_json(seen_path, {})
    crm = _load_json(data_dir / "crm.json", {"contacts": {}})
    projects_data = _load_json(data_dir / "projects.json", {"projects": {}})
    actions_data = _load_json(data_dir / "results" / "meeting_action_items.json", {"items": []})
    contacts_by_email = {e.lower(): c for e, c in (crm.get("contacts") or {}).items()}
    display_name = (settings or {}).get("display_name") or "the executive"

    new_preps: list[dict] = []
    for ev in events:
        ev_id = ev.get("id") or hashlib.sha1(((ev.get("subject", "") + (ev.get("start", {}) or {}).get("dateTime", "")).encode())).hexdigest()
        if ev_id in seen and not force_refresh:
            continue

        start_iso = (ev.get("start") or {}).get("dateTime") or ""
        try:
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        except Exception:
            continue
        # Only prep meetings within the prep window
        delta_min = (start_dt - now).total_seconds() / 60
        if delta_min < 0 or delta_min > prep_minutes + 10:
            continue

        attendees_raw = ev.get("attendees") or []
        attendee_emails = set()
        attendee_ctx: list[dict] = []
        for a in attendees_raw:
            ea = (a.get("emailAddress") or {})
            email = (ea.get("address") or "").lower()
            if not email:
                continue
            attendee_emails.add(email)
            attendee_ctx.append(_build_attendee_context(email, crm, contacts_by_email))

        related = _related_projects(attendee_emails, projects_data)
        open_actions = _open_actions_for_attendees(attendee_emails, actions_data.get("items", []))

        meeting_summary = {
            "subject":     ev.get("subject") or "(no subject)",
            "start":       start_iso,
            "start_local": format_local_time(start_iso, tz),
            "end":         (ev.get("end") or {}).get("dateTime") or "",
            "location":    (ev.get("location") or {}).get("displayName", ""),
        }

        remember = _ai_remember_hint(meeting_summary, attendee_ctx, related, open_actions, ai, display_name,
                                     user_instruction=user_instruction)

        prep = {
            "id":          hashlib.sha1(ev_id.encode()).hexdigest()[:16],
            "meeting_id":  ev_id,
            "subject":     meeting_summary["subject"],
            "start":       meeting_summary["start"],
            "start_local": meeting_summary["start_local"],
            "end":         meeting_summary["end"],
            "location":    meeting_summary["location"],
            "minutes_until": round(delta_min),
            "attendees":   attendee_ctx,
            "related_projects": related,
            "open_actions": open_actions,
            "remember":    remember,
            "teams_message": "",  # filled below
        }
        prep["teams_message"] = _format_for_teams(prep)
        new_preps.append(prep)
        seen[ev_id] = now.isoformat()
        _p(f"  Prepped: {meeting_summary['subject']} ({round(delta_min)} min out)")

    _save_json(seen_path, seen)

    result = {
        "id":       _RESULT_ID,
        "status":   "fresh",
        "last_run": now.isoformat(),
        "items":    new_preps,
        "count":    len(new_preps),
        "empty":    len(new_preps) == 0,
    }
    _save_json(results_path, result)
    return result
