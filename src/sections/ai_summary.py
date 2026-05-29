"""
ai_summary section — morning briefing synthesis layer.

Reads other sections' result.json files (refreshing them if stale) and
generates a narrative briefing. Does NOT fetch raw calendar / inbox /
screener data — that's the job of the dedicated sections.

Each dependency is refreshed if its last_run is older than FRESH_WINDOW_SECS,
otherwise reused. A matching freshness check in server._run_briefing_for_user
ensures a refreshed dep is not run twice in the same briefing.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.tz import now_local


_OVERDUE_CUTOFF_DAYS = 7  # items overdue >7d are dropped from the briefing


def _due_tag(due: str | None) -> str:
    """Inline tag the AI uses to bucket items into Today / Overdue / Coming Up.

    Items overdue more than _OVERDUE_CUTOFF_DAYS are tagged [STALE] — the
    briefing pipeline drops them in _sort_and_cap. Past a week the user has
    either consciously moved on or handled it out-of-band; surfacing them is
    noise.
    """
    if not due:
        return "[NO DATE]"
    due = str(due)[:10]
    today_iso = date.today().isoformat()
    if due < today_iso:
        try:
            days_late = (date.today() - date.fromisoformat(due)).days
            if days_late > _OVERDUE_CUTOFF_DAYS:
                return f"[STALE {days_late}d]"
            return f"[OVERDUE {days_late}d]"
        except Exception:
            return "[OVERDUE]"
    if due == today_iso:
        return "[TODAY]"
    return "[FUTURE]"

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "ai_summary" / "skill.md"

DEPENDENCIES = [
    "meetings_today",
    "reply_needed",
    "followup_needed",
    "commitments_extract",
    "due_today",
    "upcoming_commitments",
    "yesterday_recap",
    "meeting_action_items",
    "relationship_health",
    "projects_needing_attention",
]

FRESH_WINDOW_SECS = 30 * 60
_MAX_ITEMS_PER_DEP = 10
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _load_result(data_dir: Path, sid: str) -> dict:
    f = data_dir / "results" / f"{sid}.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def _save_result(data_dir: Path, sid: str, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / f"{sid}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _is_fresh(result: dict, window_secs: int) -> bool:
    ts = result.get("last_run")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() <= window_secs
    except Exception:
        return False


def _is_stale_overdue(due: str | None) -> bool:
    """True for items overdue more than _OVERDUE_CUTOFF_DAYS — dropped from briefing."""
    if not due:
        return False
    try:
        days_late = (date.today() - date.fromisoformat(str(due)[:10])).days
        return days_late > _OVERDUE_CUTOFF_DAYS
    except Exception:
        return False


def _sort_and_cap(sid: str, items: list) -> list:
    """Per-dep ranking so top-10 are the most relevant when we truncate."""
    if not items:
        return []
    if sid == "reply_needed":
        items = sorted(items, key=lambda x: (_PRIORITY_RANK.get(x.get("priority", "medium"), 1), -_recency(x.get("received"))))
    elif sid == "followup_needed":
        items = sorted(items, key=lambda x: (_PRIORITY_RANK.get(x.get("urgency", "medium"), 1), -int(x.get("days_waiting", 0) or 0)))
    elif sid in ("due_today", "upcoming_commitments"):
        items = [c for c in items if not _is_stale_overdue(c.get("due_date"))]
        items = sorted(items, key=lambda x: (x.get("due_date") or "9999", _PRIORITY_RANK.get(x.get("priority", "medium"), 1)))
    elif sid == "meeting_action_items":
        items = [a for a in items if not a.get("completed") and not _is_stale_overdue(a.get("due_date"))]
        items = sorted(items, key=lambda x: (x.get("due_date") or "9999"))
    elif sid == "relationship_health":
        items = [h for h in items if h.get("status") in ("at_risk", "cooling", "overdue")]
        items = sorted(items, key=lambda x: _PRIORITY_RANK.get(x.get("priority", "medium"), 1))
    elif sid == "projects_needing_attention":
        items = sorted(items, key=lambda x: (_PRIORITY_RANK.get(x.get("priority", "medium"), 1), x.get("last_activity") or ""))
    elif sid == "meetings_today":
        items = sorted(items, key=lambda x: x.get("start") or x.get("time") or "")
    elif sid == "yesterday_recap":
        items = sorted(items, key=lambda x: _PRIORITY_RANK.get(x.get("priority", "medium"), 1))
    return items[:_MAX_ITEMS_PER_DEP]


def _recency(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _format_atom(sid: str, idx: int, item: dict) -> str:
    if sid == "meetings_today":
        time = item.get("time") or item.get("start") or ""
        return f"  [{idx}] {time} — {item.get('subject') or item.get('title') or '(no title)'}"
    if sid == "reply_needed":
        pri = item.get("priority", "medium")
        sender = item.get("from_name") or item.get("from_email") or "Unknown"
        subj = (item.get("subject") or "(no subject)")[:80]
        reason = (item.get("reason") or item.get("preview") or "").strip()[:120]
        return f"  [{idx}] {pri.upper()} — From: {sender} | Subject: \"{subj}\" | Reason: {reason}"
    if sid == "followup_needed":
        urg = item.get("urgency", "medium")
        to = item.get("to_name") or item.get("to_email") or "Unknown"
        subj = (item.get("subject") or "(no subject)")[:80]
        days = item.get("days_waiting", 0)
        return f"  [{idx}] {urg.upper()} — To: {to} | Subject: \"{subj}\" | {days}d waiting"
    if sid in ("due_today", "upcoming_commitments"):
        desc = (item.get("description") or "")[:120]
        person = item.get("contact_name") or item.get("contact_email") or ""
        person_str = f" — {person}" if person else ""
        return f"  [{idx}] {_due_tag(item.get('due_date'))} {desc}{person_str}"
    if sid == "meeting_action_items":
        action = (item.get("action") or "")[:120]
        meeting = item.get("meeting_title") or ""
        meeting_str = f" (from: {meeting})" if meeting else ""
        return f"  [{idx}] {_due_tag(item.get('due_date'))} {action}{meeting_str}"
    if sid == "relationship_health":
        name = item.get("contact_name") or item.get("contact_email") or "Unknown"
        status = item.get("status", "")
        suggested = (item.get("suggested_action") or "")[:80]
        return f"  [{idx}] {name} — {status}" + (f" | {suggested}" if suggested else "")
    if sid == "projects_needing_attention":
        name = item.get("name") or ""
        status = item.get("status", "")
        summary = (item.get("summary") or "")[:100]
        next_action = (item.get("next_action") or "")[:160]
        base = f"  [{idx}] {name} — {status} — {summary}"
        if next_action:
            base += f"\n         NEXT: {next_action}"
        return base
    if sid == "yesterday_recap":
        kind = item.get("type", "")
        subj = (item.get("subject") or "")[:80]
        who = item.get("from") or ""
        return f"  [{idx}] {kind}: \"{subj}\"" + (f" — {who}" if who else "")
    return f"  [{idx}] {json.dumps(item, ensure_ascii=False)[:200]}"


def _format_dep_block(sid: str, dep: dict) -> str:
    if dep.get("error"):
        return f"{sid.upper()}: skipped (refresh error: {dep['error'][:80]})"
    items = _sort_and_cap(sid, dep.get("items") or [])
    if not items:
        return f"{sid.upper()}: empty"
    header = f"{sid.upper()} (count={len(items)}):"
    body = "\n".join(_format_atom(sid, i + 1, it) for i, it in enumerate(items))
    return f"{header}\n{body}"


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
    runner_lookup=None,
) -> dict:
    """Synthesise morning briefing from other sections' results.

    runner_lookup(sid) -> callable(graph, ai, data_dir, settings, progress) -> dict
    Injected from server._SECTION_RUNNERS to avoid circular import; used to
    refresh a stale dep on demand.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}

    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""
    instr_path = data_dir / "instructions" / "ai_summary.md"
    user_instruction = instr_path.read_text().strip() if instr_path.exists() else ""

    display_name = settings.get("display_name", "the executive")
    date_str = now_local(data_dir).strftime("%A, %B %d, %Y")

    deps: dict[str, dict] = {}
    source_runs: dict[str, str] = {}

    for sid in DEPENDENCIES:
        existing = _load_result(data_dir, sid)
        if existing and _is_fresh(existing, FRESH_WINDOW_SECS):
            deps[sid] = existing
            source_runs[sid] = existing.get("last_run", "")
            continue

        runner = runner_lookup(sid) if runner_lookup else None
        if not runner:
            deps[sid] = existing or {"items": []}
            source_runs[sid] = (existing or {}).get("last_run", "")
            continue

        log(f"ai_summary: refreshing {sid}...")
        try:
            result = runner(graph, ai, data_dir, settings, progress)
            _save_result(data_dir, sid, result)
            deps[sid] = result
            source_runs[sid] = result.get("last_run", "")
        except Exception as e:
            log(f"ai_summary: {sid} refresh failed: {e}")
            deps[sid] = {"items": [], "error": str(e)}

    skill_block = skill_text.replace("{display_name}", display_name).replace("{date}", date_str)
    dep_blocks = "\n\n".join(_format_dep_block(sid, deps[sid]) for sid in DEPENDENCIES)
    prompt_parts = [
        skill_block,
        f"\nTODAY'S DATE: {date_str}",
        "",
        "=== PRE-COMPUTED LISTS ===",
        "",
        dep_blocks,
    ]
    if user_instruction:
        prompt_parts += ["", "USER INSTRUCTIONS (override anything above if contradicted):", user_instruction]
    prompt = "\n".join(prompt_parts)

    log("Generating morning briefing...")
    try:
        briefing = ai.generate(prompt)
    except Exception as e:
        log(f"Briefing generation failed: {e}")
        briefing = ""

    result = {
        "id":          "ai_summary",
        "status":      "fresh",
        "last_run":    datetime.now(timezone.utc).isoformat(),
        "briefing":    briefing or "",
        "source_runs": source_runs,
        "items":       [],
        "count":       0,
        "empty":       not briefing,
    }
    _save_result(data_dir, "ai_summary", result)
    deps_with_data = sum(1 for d in deps.values() if d.get("items"))
    log(f"Morning briefing done ({deps_with_data}/{len(DEPENDENCIES)} deps with data)")
    return result
