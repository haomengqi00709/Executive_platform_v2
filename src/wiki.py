"""
Per-project wiki layer — source of truth for email metadata.

Directory layout:
  .results/wiki/
    _index.json          ← domain_map + projects registry
    techcorp.json        ← per-project with emails array
    nexuscapital.json
    ...

All derived signals (reply_needed, due_today, etc.) are computed here
from stored email records — AI only touches data at ingest and output time.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
WIKI_DIR = BASE_DIR / ".results" / "wiki"

INDEX_FILE = WIKI_DIR / "_index.json"


def _wdir(wiki_dir: Path = None) -> Path:
    d = wiki_dir or WIKI_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Private helpers ───────────────────────────────────────

def _parse_dt(s) -> datetime | None:
    """Parse an ISO datetime string into a timezone-aware datetime."""
    if not s:
        return None
    s = str(s)
    try:
        cleaned = re.sub(r'\.\d+', '', s)
        cleaned = cleaned.replace('+00:00', 'Z').replace(' ', 'T')
        if cleaned.endswith('Z'):
            cleaned = cleaned[:-1]
        return datetime.strptime(cleaned[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Index I/O ─────────────────────────────────────────────

def _load_index(wiki_dir: Path = None) -> dict:
    d = _wdir(wiki_dir)
    index_file = d / "_index.json"
    if not index_file.exists():
        return {"domain_map": {}, "projects": {}}
    try:
        return json.loads(index_file.read_text())
    except Exception:
        return {"domain_map": {}, "projects": {}}


def _save_index(index: dict, wiki_dir: Path = None):
    d = _wdir(wiki_dir)
    index_file = d / "_index.json"
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))


# ── Project registry ──────────────────────────────────────

def register_project(project_id: str, name: str, domain: str, wiki_dir: Path = None):
    """Register a project in the index. Idempotent."""
    index = _load_index(wiki_dir)
    index["domain_map"][domain.lower()] = project_id
    index["projects"][project_id] = {"name": name, "domain": domain.lower()}
    _save_index(index, wiki_dir)


def get_project_id_for_domain(domain: str, wiki_dir: Path = None) -> str | None:
    """Return project_id for a domain, or None if not registered."""
    if not domain:
        return None
    index = _load_index(wiki_dir)
    return index["domain_map"].get(domain.lower())


def list_projects(wiki_dir: Path = None) -> list[tuple[str, str]]:
    """Return list of (project_id, name) tuples from the index."""
    index = _load_index(wiki_dir)
    return [(pid, meta.get("name", pid)) for pid, meta in index["projects"].items()]


# ── Project file I/O ──────────────────────────────────────

def load_project(project_id: str, wiki_dir: Path = None) -> dict | None:
    path = _wdir(wiki_dir) / f"{project_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_project(project: dict, wiki_dir: Path = None):
    path = _wdir(wiki_dir) / f"{project['id']}.json"
    path.write_text(json.dumps(project, indent=2, ensure_ascii=False))


# ── Email ingest ──────────────────────────────────────────

def add_emails(project_id: str, name: str, domain: str, emails: list[dict], wiki_dir: Path = None) -> int:
    """
    Append new email records to a project, deduplicating by msg_id.
    Creates the project file if it doesn't exist.
    Returns count of newly added records.
    """
    project = load_project(project_id, wiki_dir)
    if project is None:
        project = {
            "id":           project_id,
            "name":         name,
            "domain":       domain.lower(),
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "contacts":     [],
            "emails":       [],
            "last_ingested": datetime.now(timezone.utc).isoformat(),
        }

    existing_ids = {e["msg_id"] for e in project.get("emails", [])}
    new_records = [e for e in emails if e.get("msg_id") and e["msg_id"] not in existing_ids]

    project.setdefault("emails", []).extend(new_records)
    project["last_ingested"] = datetime.now(timezone.utc).isoformat()

    register_project(project_id, name, domain, wiki_dir)
    save_project(project, wiki_dir)
    return len(new_records)


def update_contacts(project_id: str, contacts: list[dict], wiki_dir: Path = None):
    """Merge contacts list into the project file (dedup by email address)."""
    project = load_project(project_id, wiki_dir)
    if not project:
        return
    existing = {c["email"].lower() for c in project.get("contacts", []) if c.get("email")}
    for c in contacts:
        addr = (c.get("email") or "").lower()
        if addr and addr not in existing:
            project.setdefault("contacts", []).append(c)
            existing.add(addr)
    save_project(project, wiki_dir)


# ── Mutation helpers ──────────────────────────────────────

def mark_replied(conversation_id: str, reply_date: str, wiki_dir: Path = None):
    """
    For every project, mark inbound emails in conversation_id as replied=True
    if their date is before reply_date.
    """
    reply_dt = _parse_dt(reply_date)
    if not reply_dt:
        return

    for pid, _ in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        changed = False
        for email in project.get("emails", []):
            if (email.get("conversation_id") == conversation_id
                    and email.get("direction") == "inbound"
                    and not email.get("replied")):
                email_dt = _parse_dt(email.get("date"))
                if email_dt and email_dt < reply_dt:
                    email["replied"] = True
                    email["reply_date"] = reply_date
                    changed = True
        if changed:
            save_project(project, wiki_dir)


# ── Query functions ───────────────────────────────────────

def get_reply_needed(threshold_days: int = 3, wiki_dir: Path = None) -> list[dict]:
    """
    Return inbound emails that have not been replied to and are at least
    threshold_days old. Each item includes project_id and project_name.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=threshold_days)
    results = []

    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        for email in project.get("emails", []):
            if email.get("direction") != "inbound":
                continue
            if email.get("replied"):
                continue
            email_dt = _parse_dt(email.get("date"))
            if not email_dt or email_dt > cutoff:
                continue
            days_waiting = (now - email_dt).days
            results.append({
                **email,
                "project_id":   pid,
                "project_name": pname,
                "days_waiting": days_waiting,
            })

    results.sort(key=lambda x: x.get("days_waiting", 0), reverse=True)
    return results


def get_followup_needed(threshold_days: int = 3, wiki_dir: Path = None) -> list[dict]:
    """
    Return outbound emails where no inbound reply exists in the same conversation
    after the outbound email, and the outbound email is at least threshold_days old.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=threshold_days)
    results = []

    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue

        emails = project.get("emails", [])

        latest_inbound: dict[str, datetime] = {}
        for email in emails:
            if email.get("direction") != "inbound":
                continue
            cid = email.get("conversation_id") or ""
            if not cid:
                continue
            dt = _parse_dt(email.get("date"))
            if dt and (cid not in latest_inbound or dt > latest_inbound[cid]):
                latest_inbound[cid] = dt

        for email in emails:
            if email.get("direction") != "outbound":
                continue
            cid = email.get("conversation_id") or ""
            out_dt = _parse_dt(email.get("date"))
            if not out_dt or out_dt > cutoff:
                continue
            last_in = latest_inbound.get(cid)
            if last_in and last_in > out_dt:
                continue
            days_waiting = (now - out_dt).days
            results.append({
                **email,
                "project_id":   pid,
                "project_name": pname,
                "days_waiting": days_waiting,
            })

    results.sort(key=lambda x: x.get("days_waiting", 0), reverse=True)
    return results


def get_due_today(wiki_dir: Path = None) -> list[dict]:
    """Return emails where due_date == today."""
    today = _today_str()
    results = []
    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        for email in project.get("emails", []):
            dd = email.get("due_date") or ""
            if dd[:10] == today:
                results.append({
                    **email,
                    "project_id":   pid,
                    "project_name": pname,
                })
    return results


def get_upcoming_commitments(days: int = 7, wiki_dir: Path = None) -> list[dict]:
    """Return emails with a due_date in the next N days (including today)."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    results = []
    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        for email in project.get("emails", []):
            dd = email.get("due_date") or ""
            if not dd:
                continue
            due_dt = _parse_dt(dd + "T00:00:00Z" if len(dd) == 10 else dd)
            if due_dt and now <= due_dt <= horizon:
                results.append({
                    **email,
                    "project_id":   pid,
                    "project_name": pname,
                    "due_dt":       due_dt.isoformat(),
                })
    results.sort(key=lambda x: x.get("due_dt", ""))
    return results


def get_project_summaries(wiki_dir: Path = None) -> list[dict]:
    """
    Return computed stats per project:
    total_emails, recent_emails (last 7 days), pending_replies, last_activity.
    """
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    summaries = []

    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        emails = project.get("emails", [])
        total = len(emails)
        recent = sum(
            1 for e in emails
            if (_parse_dt(e.get("date")) or datetime.min.replace(tzinfo=timezone.utc)) >= week_ago
        )
        pending = sum(
            1 for e in emails
            if e.get("direction") == "inbound" and not e.get("replied")
        )
        dates = [_parse_dt(e.get("date")) for e in emails]
        dates = [d for d in dates if d]
        last_activity = max(dates).isoformat() if dates else None

        summaries.append({
            "project_id":      pid,
            "project_name":    pname,
            "domain":          project.get("domain", ""),
            "total_emails":    total,
            "recent_emails":   recent,
            "pending_replies": pending,
            "last_activity":   last_activity,
        })

    summaries.sort(key=lambda x: x.get("last_activity") or "", reverse=True)
    return summaries


def get_attention_projects(wiki_dir: Path = None, ignored_emails: set = None) -> list[dict]:
    """
    Projects with at least one pending inbound email from a non-ignored contact.
    A project is excluded only if ALL its pending emails come from ignored contacts.
    """
    ignored = {e.lower() for e in (ignored_emails or ())}
    results = []

    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        emails = project.get("emails", [])
        pending_non_ignored = sum(
            1 for e in emails
            if e.get("direction") == "inbound"
            and not e.get("replied")
            and e.get("from", "").lower() not in ignored
        )
        if pending_non_ignored == 0:
            continue
        dates = [_parse_dt(e.get("date")) for e in emails]
        dates = [d for d in dates if d]
        results.append({
            "project_id":      pid,
            "project_name":    pname,
            "domain":          project.get("domain", ""),
            "pending_replies": pending_non_ignored,
            "last_activity":   max(dates).isoformat() if dates else None,
        })

    results.sort(key=lambda x: x.get("pending_replies", 0), reverse=True)
    return results


# ── Meeting ingest ────────────────────────────────────────

def add_meeting(project_id: str, meeting: dict, wiki_dir: Path = None) -> bool:
    """
    Add a meeting record to a project. Deduplicates by meeting_id.
    Returns True if newly added, False if already existed.
    """
    project = load_project(project_id, wiki_dir)
    if not project:
        return False
    existing_ids = {m["meeting_id"] for m in project.get("meetings", [])}
    if meeting["meeting_id"] in existing_ids:
        return False
    project.setdefault("meetings", []).append(meeting)
    save_project(project, wiki_dir)
    return True


def get_recent_meetings(days: int = 7, wiki_dir: Path = None) -> list[dict]:
    """Return all meetings from the last N days across all projects, newest first."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    results = []
    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        for m in project.get("meetings", []):
            dt = _parse_dt(m.get("date") + "T00:00:00Z" if len(m.get("date", "")) == 10 else m.get("date", ""))
            if dt and dt >= cutoff:
                results.append({**m, "project_id": pid, "project_name": pname})
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results


def get_meeting_action_items(days: int = 14, wiki_dir: Path = None) -> list[dict]:
    """Return all action items from meetings in the last N days, with project context."""
    meetings = get_recent_meetings(days=days, wiki_dir=wiki_dir)
    results = []
    for m in meetings:
        for item in m.get("action_items", []):
            results.append({
                **item,
                "meeting_title":  m.get("title", ""),
                "meeting_date":   m.get("date", ""),
                "project_id":     m.get("project_id", ""),
                "project_name":   m.get("project_name", ""),
            })
    return results


# ── Date-range query ─────────────────────────────────────

def get_emails_by_date(date_str: str, wiki_dir: Path = None) -> list[dict]:
    """Return all inbound emails received on date_str (YYYY-MM-DD), sorted newest first."""
    results = []
    for pid, pname in list_projects(wiki_dir):
        project = load_project(pid, wiki_dir)
        if not project:
            continue
        for email in project.get("emails", []):
            if email.get("direction") != "inbound":
                continue
            if (email.get("date") or "")[:10] == date_str:
                results.append({**email, "project_id": pid, "project_name": pname})
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results


# ── Text output for M01 ───────────────────────────────────

def get_briefing_context(wiki_dir: Path = None) -> str:
    """
    Return a formatted text block of project summaries for M01 prompts.
    """
    summaries = get_project_summaries(wiki_dir)
    if not summaries:
        return "No project data available."

    lines = []
    for s in summaries:
        pending_flag = " [PENDING REPLIES]" if s["pending_replies"] > 0 else ""
        activity = s["last_activity"][:10] if s["last_activity"] else "unknown"
        lines.append(
            f"[{s['project_id']}] {s['project_name']}{pending_flag}\n"
            f"  Domain: {s['domain']} | Emails: {s['total_emails']} total, "
            f"{s['recent_emails']} last 7d | Pending replies: {s['pending_replies']} | "
            f"Last activity: {activity}"
        )

    return "\n\n".join(lines)


def format_pending_for_briefing(wiki_dir: Path = None) -> str:
    """Return a text block of pending email actions for M01 LLM prompt."""
    lines = []

    reply = get_reply_needed(wiki_dir=wiki_dir)
    if reply:
        lines.append("EMAILS AWAITING YOUR REPLY:")
        for r in reply[:8]:
            proj = f" [{r.get('project_name', '')}]" if r.get("project_name") else ""
            lines.append(
                f"  - {r['days_waiting']}d overdue — \"{r.get('subject', '(no subject)')}\" "
                f"from {r.get('from', '')}{proj}"
            )

    followup = get_followup_needed(wiki_dir=wiki_dir)
    if followup:
        lines.append("SENT EMAILS WITH NO RESPONSE (follow-up needed):")
        for f in followup[:8]:
            proj = f" [{f.get('project_name', '')}]" if f.get("project_name") else ""
            lines.append(
                f"  - {f['days_waiting']}d no response — \"{f.get('subject', '(no subject)')}\" "
                f"to {f.get('to', '')}{proj}"
            )

    return "\n".join(lines) if lines else ""


# ── Init check ────────────────────────────────────────────

def needs_init_scan(wiki_dir: Path = None) -> bool:
    """Return True if _index.json has no projects registered yet."""
    index = _load_index(wiki_dir)
    return len(index.get("projects", {})) == 0
