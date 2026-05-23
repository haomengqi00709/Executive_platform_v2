"""
ai_summary section — morning briefing.

Four-layer input:
  1. src/skills/ai_summary.md          — system skill description (stable)
  2. data_dir/instructions/ai_summary.md — user temp instructions (optional)
  3. Live fetch: calendar + screened inbox
  4. Other section results: commitments_extract, meeting_action_items, relationship_health
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.screener import screen_emails
from src.modules.crm import load_crm
from src.modules.projects import load_projects
from src.modules.profile import load_profile_context

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "ai_summary" / "skill.md"

_WIN_TZ = {
    "Eastern Standard Time":        "America/New_York",
    "Eastern Daylight Time":        "America/New_York",
    "Central Standard Time":        "America/Chicago",
    "Mountain Standard Time":       "America/Denver",
    "Pacific Standard Time":        "America/Los_Angeles",
    "Pacific Daylight Time":        "America/Los_Angeles",
    "Atlantic Standard Time":       "America/Halifax",
    "Newfoundland Standard Time":   "America/St_Johns",
    "Saskatchewan":                 "America/Regina",
    "Canada Central Standard Time": "America/Regina",
    "GMT Standard Time":            "Europe/London",
    "China Standard Time":          "Asia/Shanghai",
    "Tokyo Standard Time":          "Asia/Tokyo",
    "AUS Eastern Standard Time":    "Australia/Sydney",
}


def _resolve_tz(raw: str) -> ZoneInfo:
    iana = _WIN_TZ.get(raw, raw if "/" in raw else "UTC")
    try:
        return ZoneInfo(iana)
    except Exception:
        return ZoneInfo("UTC")


def _fmt_time(utc_str: str, tz: ZoneInfo) -> str:
    try:
        s = utc_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%H:%M")
    except Exception:
        return utc_str[11:16] if len(utc_str) > 15 else utc_str


def _load_result(data_dir: Path, section_id: str) -> dict:
    f = data_dir / "results" / f"{section_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / "ai_summary.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
) -> dict:
    """
    Generate morning briefing for the executive.

    Returns standard section result dict with briefing text + structured data.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}

    # ── 1. Skill description ──────────────────────────────
    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""

    # ── 2. User instruction ───────────────────────────────
    instruction_path = data_dir / "instructions" / "ai_summary.md"
    user_instruction = instruction_path.read_text().strip() if instruction_path.exists() else ""

    # ── 3. Timezone + today's window ─────────────────────
    tz_raw = settings.get("timezone") or ""
    if not tz_raw:
        try:
            tz_raw = graph.get_mailbox_timezone()
        except Exception:
            tz_raw = "UTC"

    tz = _resolve_tz(tz_raw)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    today_utc = today_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tomorrow_utc = tomorrow_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now_local.strftime("%A, %B %d, %Y")

    display_name = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir)

    # ── 4. Calendar ───────────────────────────────────────
    log("Fetching today's calendar...")
    try:
        events = graph.get_calendar_view(today_utc, tomorrow_utc, top=20)
    except Exception as e:
        log(f"Calendar fetch failed: {e}")
        events = []

    # ── 5. Screened inbox (last 2 days) ───────────────────
    log("Fetching recent emails...")
    try:
        raw_messages = graph.get_messages_since(days=2, max_results=200)
    except Exception as e:
        log(f"Inbox fetch failed: {e}")
        raw_messages = []

    ignored_emails: set = set()
    try:
        crm_data = load_crm(data_dir)
        ignored_emails = {
            email for email, c in crm_data.get("contacts", {}).items()
            if c.get("ignore") or c.get("priority") == "ignore"
        }
    except Exception:
        pass

    if raw_messages:
        log(f"Screening {len(raw_messages)} emails...")
        screened = screen_emails(
            messages=raw_messages,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=business_context,
            display_name=display_name,
            progress=progress,
        )
        visible = [m for m in screened if not m.get("screened_out")]
    else:
        visible = []

    top_emails = visible[:15]

    # ── 6. Other section results (optional context) ───────
    commitments_data = _load_result(data_dir, "commitments_extract")
    action_items_data = _load_result(data_dir, "meeting_action_items")
    health_data = _load_result(data_dir, "relationship_health")

    today_str = now_local.strftime("%Y-%m-%d")
    next_week_str = (now_local + timedelta(days=7)).strftime("%Y-%m-%d")

    # Filter commitments to today + next 7 days
    all_commitments = commitments_data.get("items", [])
    due_soon = [
        c for c in all_commitments
        if today_str <= (c.get("due_date") or "9999")[:10] <= next_week_str
    ]

    # Open meeting action items
    all_actions = action_items_data.get("items", [])
    open_actions = [a for a in all_actions if not a.get("completed")][:10]

    # At-risk relationships
    all_health = health_data.get("items", [])
    at_risk = [h for h in all_health if h.get("status") in ("at_risk", "overdue")][:5]

    # Stalled / at-risk projects from projects.json
    projects_db = load_projects(data_dir)
    all_projects = list(projects_db.get("projects", {}).values())
    cutoff_str = (now_local - timedelta(days=30)).strftime("%Y-%m-%d")
    attention_projects = [
        p for p in all_projects
        if p.get("status") in ("stalled", "at_risk")
        and not p.get("ignore") and p.get("priority") != "ignore"
        and (p.get("last_activity") or "9999") >= cutoff_str
    ][:5]

    # ── 7. Build prompt ───────────────────────────────────
    skill_block = skill_text.replace("{display_name}", display_name).replace("{date}", date_str)

    if events:
        event_lines = "\n".join(
            f"- {'All day' if e.get('isAllDay') else _fmt_time(e.get('start', {}).get('dateTime', ''), tz)} — {e.get('subject', '(no subject)')}"
            for e in events
        )
    else:
        event_lines = ""

    if top_emails:
        email_lines = "\n".join(
            f"- From: {((m.get('from') or {}).get('emailAddress') or {}).get('name') or ((m.get('from') or {}).get('emailAddress') or {}).get('address', '')} | "
            f"Subject: {(m.get('subject') or '(no subject)')[:80]} | "
            f"Preview: {(m.get('bodyPreview') or '')[:120]}"
            for m in top_emails
        )
    else:
        email_lines = ""

    commitment_lines = "\n".join(
        f"- [{c.get('due_date', '')[:10]}] {c.get('subject', '')} — {c.get('person', '')}"
        for c in due_soon
    ) if due_soon else ""

    action_lines = "\n".join(
        f"- {a.get('action', '')} (from: {a.get('meeting_title', '')})"
        for a in open_actions
    ) if open_actions else ""

    health_lines = "\n".join(
        f"- {h.get('name', '')} <{h.get('email', '')}> — last contact: {h.get('last_contact', 'unknown')}"
        for h in at_risk
    ) if at_risk else ""

    project_lines = "\n".join(
        f"- {p.get('name', '')} ({p.get('category', '')}) — {p.get('status', '')} — \"{p.get('summary', '')}\""
        for p in attention_projects
    ) if attention_projects else ""

    prompt_parts = [skill_block, f"\nTODAY'S DATE: {date_str} ({tz_raw or 'UTC'})"]

    if event_lines:
        prompt_parts.append(f"\nTODAY'S MEETINGS:\n{event_lines}")
    if email_lines:
        prompt_parts.append(f"\nRECENT EMAILS (screened, last 2 days — top {len(top_emails)}):\n{email_lines}")
    if commitment_lines:
        prompt_parts.append(f"\nCOMMITMENTS DUE THIS WEEK:\n{commitment_lines}")
    if action_lines:
        prompt_parts.append(f"\nOPEN MEETING ACTION ITEMS:\n{action_lines}")
    if health_lines:
        prompt_parts.append(f"\nAT-RISK RELATIONSHIPS:\n{health_lines}")
    if project_lines:
        prompt_parts.append(f"\nPROJECTS NEEDING ATTENTION:\n{project_lines}")
    if user_instruction:
        prompt_parts.append(f"\nUSER INSTRUCTIONS (override anything above if contradicted):\n{user_instruction}")

    prompt = "\n".join(prompt_parts)

    # ── 8. Generate briefing ──────────────────────────────
    log("Generating morning briefing...")
    try:
        briefing = ai.generate(prompt)
    except Exception as e:
        log(f"Briefing generation failed: {e}")
        briefing = ""

    # ── 9. Write result ───────────────────────────────────
    result = {
        "id":          "ai_summary",
        "status":      "fresh",
        "last_run":    datetime.now(timezone.utc).isoformat(),
        "briefing":    briefing,
        "events":      events,
        "top_emails":  [
            {
                "subject": m.get("subject", ""),
                "from":    ((m.get("from") or {}).get("emailAddress") or {}).get("address", ""),
                "from_name": ((m.get("from") or {}).get("emailAddress") or {}).get("name", ""),
                "preview": m.get("bodyPreview", ""),
                "received": m.get("receivedDateTime", ""),
            }
            for m in top_emails
        ],
        "action_items": open_actions,
        "items":       [],
        "count":       0,
        "empty":       not briefing,
    }

    _save_result(data_dir, result)
    log(f"Morning briefing done ({len(events)} meetings, {len(top_emails)} emails)")
    return result
