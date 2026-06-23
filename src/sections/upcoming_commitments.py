"""
upcoming_commitments section — derived view of the commitments store.

Base = visible my_commitments with a due_date within the next N days (overdue included),
queried live from the store. Meeting action items (external, not store-owned) are merged in,
overdue flags computed, then sorted. No AI, no state file.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.tz import now_local
from src.modules.text_utils import is_attendance_action_item


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / "upcoming_commitments.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
) -> dict:
    """Derive upcoming commitments from the store. Returns standard section result dict."""
    def log(msg: str):
        if progress:
            progress(msg)

    from src.modules import commitments_store as store
    data_dir = Path(data_dir)
    settings = settings or {}
    window_days = int(settings.get("upcoming_commitments_days") or 7)

    today = now_local(data_dir).date()
    cutoff = today + timedelta(days=window_days)
    today_str = today.strftime("%Y-%m-%d")
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # ── 1. Base: visible my_commitments due within the window (overdue included) ──
    all_commitments = store.query_upcoming(data_dir, today_str, cutoff_str)
    log(f"Reading {len(all_commitments)} upcoming commitments from store")

    # ── 2. Merge meeting_action_items where the owner is the user ─────
    meeting_items_path = data_dir / "results" / "meeting_action_items.json"
    meeting_data = _load_json(meeting_items_path)
    exec_name = (settings.get("display_name") or "").strip().lower()
    exec_first = exec_name.split()[0] if exec_name else ""
    for item in meeting_data.get("items", []):
        if not item.get("due_date"):
            continue
        owner = (item.get("owner") or "").strip().lower()
        if exec_first and owner and exec_first not in owner and owner not in exec_first:
            continue
        all_commitments.append({
            "id":          item.get("id") or item.get("meeting_id", "") + "_" + str(hash(item.get("action", "")))[-8:],
            "type":        "my_commitment",
            "description": item.get("action", ""),
            "due_date":    item.get("due_date"),
            "due_date_confidence": "stated",
            "contact_name": item.get("meeting_title", ""),
            "priority":    "medium",
            "source":      "meeting",
            "meeting_title": item.get("meeting_title", ""),
        })

    # ── 3. Filter ─────────────────────────────────────────
    items = []
    priority_order = {"high": 0, "medium": 1, "low": 2}

    for c in all_commitments:
        if c.get("type") != "my_commitment":
            continue
        due = c.get("due_date")
        if not due:
            continue
        if due > cutoff_str:
            continue
        # A past-due attendance item already happened — not actionable, drop it.
        if due < today_str and is_attendance_action_item(c.get("description", "")):
            continue

        item = {**c, "source": c.get("source", "email")}
        if due < today_str:
            item["priority"] = "high"
            item["overdue"] = True
        else:
            item["overdue"] = False
        items.append(item)

    log(f"{len(items)} upcoming commitments (window: {window_days} days)")

    # ── 4. Sort: overdue first, then due_date asc, then priority ─
    items.sort(key=lambda x: (
        0 if x.get("overdue") else 1,
        x.get("due_date") or "9999-99-99",
        priority_order.get(x.get("priority", "medium"), 1),
    ))

    result = {
        "id":          "upcoming_commitments",
        "status":      "fresh",
        "last_run":    datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "items":       items,
        "count":       len(items),
        "empty":       len(items) == 0,
    }
    _save_result(data_dir, result)
    overdue_count = sum(1 for x in items if x.get("overdue"))
    log(f"Upcoming commitments done — {len(items)} items ({overdue_count} overdue)")
    return result
