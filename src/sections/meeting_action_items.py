"""
meeting_action_items section — reads from Meeting DB (wiki/).
Pure read layer, no processing.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.modules.wiki import get_meeting_action_items


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = Path(data_dir) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "meeting_action_items.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(path)


def run(data_dir: Path, days: int = 14, save: bool = True) -> dict:
    wiki_dir = Path(data_dir) / "wiki"
    items = get_meeting_action_items(wiki_dir, days=days)

    result = {
        "id":       "meeting_action_items",
        "status":   "fresh" if items else "not_run",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }
    if save:
        _save_result(data_dir, result)
    return result
