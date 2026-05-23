"""
recent_meetings section — reads from Meeting DB (wiki/).
Pure read layer, no processing.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.modules.wiki import get_recent_meetings


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = Path(data_dir) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "recent_meetings.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(path)


def run(data_dir: Path, days: int = 14, save: bool = True) -> dict:
    wiki_dir = Path(data_dir) / "wiki"
    meetings = get_recent_meetings(wiki_dir, days=days)

    result = {
        "id":       "recent_meetings",
        "status":   "fresh" if meetings else "not_run",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "items":    meetings,
        "count":    len(meetings),
        "empty":    len(meetings) == 0,
    }
    if save:
        _save_result(data_dir, result)
    return result
