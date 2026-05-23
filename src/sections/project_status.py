"""
project_status section — Scheduled.

Full portfolio overview of all non-completed, non-ignored projects from projects.json.
Grouped/sorted by status; minimal per-item info — meant as an at-a-glance dashboard
view, not a deep dive (use projects_needing_attention for action items).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output

_RESULT_ID = "project_status"

_INCLUDED_STATUSES = {"ongoing", "needs_attention", "paused", "early_stage"}
_STATUS_RANK = {"needs_attention": 0, "ongoing": 1, "paused": 2, "early_stage": 3}

_DEFAULT_INSTRUCTION = """\
# Project Status — User Preferences

Customise which projects appear in your Project Status digest.

## Examples

- "Skip Nexus Capital AI Strategy" — drop matching item
- "Hide all internal projects" — drop items with category=internal
- "Only client-facing projects" — drop anything that isn't a client_deal
- "Show only at-risk and slowing" — drop the rest

Anything you write here is enforced by the validator AI on every run.
"""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / f"{_RESULT_ID}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _build_item(proj: dict) -> dict:
    status = proj.get("status", "")
    key = (proj.get("id") or "") + "|status_view"
    return {
        "id":            hashlib.sha1(key.encode()).hexdigest()[:16],
        "project_id":    proj.get("id", ""),
        "name":          proj.get("name", ""),
        "category":      proj.get("category", ""),
        "status":        status,
        "momentum":      proj.get("momentum", ""),
        "summary":       (proj.get("summary") or "")[:300],
        "last_activity": proj.get("last_activity", ""),
        "deadline":      proj.get("deadline"),
        "participant_count": len(proj.get("participants", [])),
        "thread_count":  proj.get("thread_count", 0),
        "priority":      "medium",  # this section is informational, no urgency tagging
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
        print(f"[project_status] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    proj_path = data_dir / "projects.json"
    if not proj_path.exists():
        _p("projects.json missing — build projects first")
        result = {
            "id":       _RESULT_ID,
            "status":   "not_run",
            "last_run": now.isoformat(),
            "items":    [],
            "count":    0,
            "empty":    True,
            "empty_reason": "no_projects_db",
        }
        results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    try:
        data = json.loads(proj_path.read_text())
    except Exception as e:
        _p(f"Failed to read projects.json: {e}")
        data = {"projects": {}}

    projects = data.get("projects", {})
    candidates = [
        p for p in projects.values()
        if not p.get("ignore") and p.get("status") in _INCLUDED_STATUSES
    ]
    candidates.sort(key=lambda p: (
        _STATUS_RANK.get(p.get("status", ""), 9),
        -_ts(p.get("last_activity", "")),
    ) if False else (
        _STATUS_RANK.get(p.get("status", ""), 9),
    ))
    candidates.sort(key=lambda p: p.get("last_activity") or "", reverse=True)
    candidates.sort(key=lambda p: _STATUS_RANK.get(p.get("status", ""), 9))

    items = [_build_item(p) for p in candidates]

    _p(f"{len(items)} project(s) before user-preference review")

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

    status_counts: dict = {}
    for it in items:
        s = it.get("status", "")
        status_counts[s] = status_counts.get(s, 0) + 1

    _p(f"{len(items)} project(s) in portfolio after review: {status_counts}")

    result = {
        "id":       _RESULT_ID,
        "status":   "fresh",
        "last_run": now.isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
        "status_counts": status_counts,
        "total_projects": len(projects),
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def _ts(s: str) -> int:
    return int(s.replace("-", "")) if s and "-" in s else 0
