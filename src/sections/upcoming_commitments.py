"""
upcoming_commitments section — derived view of commitments_extract.

No AI. Reads commitments_extract.json, filters to:
  - type == "my_commitment"
  - due_date within the next N days (default 7), OR already overdue
  - due_date must be set (null entries excluded)

Future: when M3 is ready, meeting_action_items.json action items
with due_dates will be merged in as source="meeting".
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.commitments_state import load_state, should_show, expire_asked, save_state


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
    """
    Derive upcoming commitments from commitments_extract.json.
    Returns standard section result dict.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}
    window_days = int(settings.get("upcoming_commitments_days") or 7)

    today = datetime.now().date()
    cutoff = today + timedelta(days=window_days)
    today_str = today.strftime("%Y-%m-%d")
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # ── 1. Read commitments_extract result ────────────────
    extract_path = data_dir / "results" / "commitments_extract.json"
    extract_data = _load_json(extract_path)

    if extract_data.get("status") not in ("fresh", "stale"):
        log("commitments_extract not yet run — returning not_run")
        result = {
            "id": "upcoming_commitments", "status": "not_run",
            "last_run": None, "window_days": window_days,
            "items": [], "count": 0, "empty": True,
        }
        _save_result(data_dir, result)
        return result

    all_commitments = extract_data.get("items", [])
    log(f"Reading {len(all_commitments)} commitments from commitments_extract")

    # ── 1b. Apply state filter (done / asked / snoozed) ───
    state = load_state(data_dir)
    expired = expire_asked(state)
    if expired:
        save_state(data_dir, state)
    all_commitments = [c for c in all_commitments if should_show(c["id"], state, today_str)]

    # ── 2. (Future) Merge meeting_action_items ────────────
    meeting_items_path = data_dir / "results" / "meeting_action_items.json"
    meeting_data = _load_json(meeting_items_path)
    for item in meeting_data.get("items", []):
        if item.get("due_date") and item.get("assignee") == "executive":
            all_commitments.append({
                **item,
                "source": "meeting",
                "type": "my_commitment",
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
        # Include if overdue OR within window
        if due > cutoff_str:
            continue

        item = {**c, "source": c.get("source", "email")}

        # Force high priority for overdue items
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
