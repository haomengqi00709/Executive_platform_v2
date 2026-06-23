"""
due_today section — derived view of the commitments store.

Queries the live store for `due_date == today` AND `type == "my_commitment"` AND visible
(not done/snoozed/asked), then applies the user-preference validator. No AI extraction, no
own cache — the store is the single source of truth.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.tz import now_local, today_local_str

_RESULT_ID = "due_today"

_DEFAULT_INSTRUCTION = """\
# Due Today — User Preferences

Customise which commitments appear. Examples:

- "Only high-priority commitments"
- "Skip anything related to internal admin"
- "Drop commitments where contact is a personal email"
"""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / f"{_RESULT_ID}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


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
        print(f"[due_today] {msg}")

    from src.modules import commitments_store as store
    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    today_str = today_local_str(data_dir)

    items = store.query_due_today(data_dir, today_str)
    items.sort(key=lambda x: (
        {"high": 0, "medium": 1, "low": 2}.get(x.get("priority", "medium"), 1),
        x.get("received", ""),
    ))
    _p(f"{len(items)} item(s) before user-preference review")

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
    _p(f"Done — {len(items)} item(s) due today")
    return result
