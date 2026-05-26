"""
projects_needing_attention section — Scheduled.

Surfaces projects from projects.json whose status indicates they need executive
attention: at_risk, stalled, or new. Pure data filter — no AI, no Graph call.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output

_RESULT_ID = "projects_needing_attention"

_ATTENTION_STATUSES = {"needs_attention", "early_stage"}
_STATUS_RANK = {"needs_attention": 0, "early_stage": 1}
_MOMENTUM_RANK = {"stalled": 0, "slowing": 1, "steady": 2, "accelerating": 3}

_DEFAULT_INSTRUCTION = """\
# Projects Needing Attention — User Preferences

Customise which projects appear here. Examples:

- "Skip BuildRight — Digital Transformation Roadmap"
- "Hide internal projects"
- "Only client deals — drop everything else"
- "Promote anything tied to Nexus Capital to high priority"

Anything you write is enforced by the validator AI on every run.
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
    if status == "needs_attention":
        priority = "high"
    else:  # early_stage
        priority = "medium"

    key = (proj.get("id") or "") + "|" + status
    return {
        "id":            hashlib.sha1(key.encode()).hexdigest()[:16],
        "project_id":    proj.get("id", ""),
        "name":          proj.get("name", ""),
        "category":      proj.get("category", ""),
        "status":        status,
        "momentum":      proj.get("momentum", ""),
        "summary":       (proj.get("summary") or "")[:400],
        "next_action":   (proj.get("next_action") or "")[:300],
        "last_activity": proj.get("last_activity", ""),
        "deadline":      proj.get("deadline"),
        "participants":  proj.get("participants", [])[:8],
        "participant_count": len(proj.get("participants", [])),
        "thread_count":  proj.get("thread_count", 0),
        "priority":      priority,
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
        print(f"[projects_needing_attention] {msg}")

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
    candidates = []
    for proj in projects.values():
        if proj.get("ignore") or proj.get("archived"):
            continue
        if proj.get("status") not in _ATTENTION_STATUSES:
            continue
        candidates.append(proj)

    candidates.sort(key=lambda p: (
        _STATUS_RANK.get(p.get("status", ""), 9),
        _MOMENTUM_RANK.get(p.get("momentum", ""), 9),
        -(p.get("last_activity") or ""),  # newer activity first
    ) if False else (
        _STATUS_RANK.get(p.get("status", ""), 9),
        _MOMENTUM_RANK.get(p.get("momentum", ""), 9),
    ))
    candidates.sort(key=lambda p: p.get("last_activity") or "", reverse=True)
    candidates.sort(key=lambda p: (
        _STATUS_RANK.get(p.get("status", ""), 9),
        _MOMENTUM_RANK.get(p.get("momentum", ""), 9),
    ))

    items = [_build_item(p) for p in candidates]

    _p(f"Surfaced {len(items)} candidate(s) before user-preference review "
       f"(out of {len(projects)} total)")

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

    _p(f"{len(items)} project(s) needing attention after review")

    result = {
        "id":       _RESULT_ID,
        "status":   "fresh",
        "last_run": now.isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
        "total_projects": len(projects),
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result
