"""
commitments_state — per-user commitment completion tracking.

State file: data_dir/commitments_state.json
  done:    {id: {at, method}}           — permanently resolved
  asked:   {id: {asked_at, expires_at}} — check-in sent, awaiting response
  snoozed: {id: {until}}               — hidden until date

Public API (used by sections, bot, and M3 CLI monitors):
  load_state(data_dir)
  save_state(data_dir, state)
  should_show(commitment_id, state, today_str) -> bool
  expire_asked(state) -> list[str]      — returns IDs that just expired
  mark_done(data_dir, cid, method)
  mark_done_by_email_id(data_dir, email_id, method) -> int
  mark_asked(data_dir, cid, expire_hours)
  mark_snoozed(data_dir, cid, days)
  get_open_ids(data_dir) -> set[str]
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


_FILENAME = "commitments_state.json"


def load_state(data_dir: Path) -> dict:
    path = Path(data_dir) / _FILENAME
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def save_state(data_dir: Path, state: dict) -> None:
    path = Path(data_dir) / _FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _ensure_keys(state: dict) -> dict:
    state.setdefault("done", {})
    state.setdefault("asked", {})
    state.setdefault("snoozed", {})
    return state


def expire_asked(state: dict) -> list[str]:
    """
    Check asked items whose expires_at has passed.
    Moves them to done (method=auto_expired).
    Returns list of IDs that just expired.
    """
    _ensure_keys(state)
    now = datetime.now(timezone.utc).isoformat()
    expired = [
        cid for cid, info in state["asked"].items()
        if (info.get("expires_at") or "") < now
    ]
    for cid in expired:
        state["done"][cid] = {
            "at": now,
            "method": "auto_expired",
        }
        del state["asked"][cid]
    return expired


def should_show(commitment_id: str, state: dict, today_str: str = "") -> bool:
    """
    Return False if this commitment should be hidden:
      - in done
      - in asked (check-in already sent — hide until resolved or expired)
      - in snoozed with until >= today
    """
    _ensure_keys(state)
    if commitment_id in state["done"]:
        return False
    if commitment_id in state["asked"]:
        return False
    if commitment_id in state["snoozed"]:
        until = state["snoozed"][commitment_id].get("until", "")
        today = today_str or datetime.now().strftime("%Y-%m-%d")
        if until >= today:
            return False
        # Snooze expired — remove it so the item surfaces again
        del state["snoozed"][commitment_id]
    return True


def mark_done(data_dir: Path, commitment_id: str, method: str = "user") -> None:
    state = load_state(data_dir)
    _ensure_keys(state)
    state["done"][commitment_id] = {
        "at":     datetime.now(timezone.utc).isoformat(),
        "method": method,
    }
    state["asked"].pop(commitment_id, None)
    state["snoozed"].pop(commitment_id, None)
    save_state(data_dir, state)


def mark_done_by_email_id(data_dir: Path, email_id: str, method: str = "email_monitor") -> int:
    """
    Mark all commitments whose source email_id matches as done.
    Called by email monitor / send monitor in M3 CLI.
    Returns number of commitments marked.
    """
    # Load the extracted commitments to find matching IDs
    results_path = Path(data_dir) / "results" / "commitments_extract.json"
    try:
        data = json.loads(results_path.read_text()) if results_path.exists() else {}
    except Exception:
        return 0

    matching_ids = [
        item["id"] for item in data.get("items", [])
        if item.get("email_id") == email_id and item.get("id")
    ]

    if not matching_ids:
        return 0

    state = load_state(data_dir)
    _ensure_keys(state)
    now = datetime.now(timezone.utc).isoformat()
    for cid in matching_ids:
        state["done"][cid] = {"at": now, "method": method}
        state["asked"].pop(cid, None)
        state["snoozed"].pop(cid, None)

    save_state(data_dir, state)
    return len(matching_ids)


def mark_asked(data_dir: Path, commitment_id: str, expire_hours: int = 24) -> None:
    state = load_state(data_dir)
    _ensure_keys(state)
    if commitment_id in state["done"]:
        return
    now = datetime.now(timezone.utc)
    state["asked"][commitment_id] = {
        "asked_at":   now.isoformat(),
        "expires_at": (now + timedelta(hours=expire_hours)).isoformat(),
    }
    save_state(data_dir, state)


def mark_snoozed(data_dir: Path, commitment_id: str, days: int = 3) -> None:
    state = load_state(data_dir)
    _ensure_keys(state)
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    state["snoozed"][commitment_id] = {"until": until}
    state["asked"].pop(commitment_id, None)
    save_state(data_dir, state)


def get_open_ids(data_dir: Path) -> set[str]:
    """
    Return commitment IDs that are not done/asked/snoozed.
    Used by M3 CLI monitors to check which commitments are still open.
    """
    results_path = Path(data_dir) / "results" / "commitments_extract.json"
    try:
        data = json.loads(results_path.read_text()) if results_path.exists() else {}
    except Exception:
        return set()

    all_ids = {item["id"] for item in data.get("items", []) if item.get("id")}
    state = load_state(data_dir)
    _ensure_keys(state)
    today = datetime.now().strftime("%Y-%m-%d")

    hidden = set(state["done"].keys()) | set(state["asked"].keys())
    for cid, info in state["snoozed"].items():
        if (info.get("until") or "") >= today:
            hidden.add(cid)

    return all_ids - hidden
