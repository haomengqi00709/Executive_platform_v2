"""requests.json persistence for the feedback-board.

Atomic JSON writes (tmp + replace), same pattern as ops-dashboard/src/state.py.

One file in DATA_DIR (env, default ./data):
  requests.json  — {"next_seq": N, "requests": [ {request}, ... ]}

A request:
  {
    "id": "REQ-7",
    "kind": "bug" | "feature" | "optimization",
    "title": "...",
    "body": "...",
    "author": "...",
    "chat_context": "...optional Q&A that led to this...",
    "status": "new" | "in_progress" | "done",
    "created_at": iso, "updated_at": iso,
    "history": [ {"at": iso, "actor": "...", "action": "..."} ]
  }
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
REQUESTS_PATH = DATA_DIR / "requests.json"

KINDS = ("bug", "feature", "optimization")
STATUSES = ("new", "in_progress", "done")
_DEFAULT = {"next_seq": 1, "requests": []}


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read() -> dict:
    if not REQUESTS_PATH.exists():
        return dict(_DEFAULT, requests=[])
    try:
        data = json.loads(REQUESTS_PATH.read_text())
        if not isinstance(data, dict) or "requests" not in data:
            return dict(_DEFAULT, requests=[])
        data.setdefault("next_seq", 1)
        return data
    except Exception:
        return dict(_DEFAULT, requests=[])


def _write(data: dict):
    _ensure_data_dir()
    tmp = REQUESTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(REQUESTS_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seq_of(req_id: str) -> int:
    m = re.match(r"REQ-(\d+)$", req_id or "")
    return int(m.group(1)) if m else -1


def list_requests() -> list:
    """All requests, newest first (highest REQ number first)."""
    reqs = _read()["requests"]
    return sorted(reqs, key=lambda r: _seq_of(r.get("id", "")), reverse=True)


def get_request(req_id: str) -> dict | None:
    for r in _read()["requests"]:
        if r.get("id") == req_id:
            return r
    return None


def add_request(kind: str, title: str, body: str, author: str,
                chat_context: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")

    data = _read()
    # Allocate next id from a monotonic counter that also respects the max
    # existing id, so a hand-edited file can never collide.
    max_existing = max((_seq_of(r.get("id", "")) for r in data["requests"]), default=0)
    seq = max(data.get("next_seq", 1), max_existing + 1)
    now = _now()
    req = {
        "id": f"REQ-{seq}",
        "kind": kind,
        "title": title,
        "body": (body or "").strip(),
        "author": (author or "anonymous").strip() or "anonymous",
        "chat_context": (chat_context or "").strip() or None,
        "status": "new",
        "created_at": now,
        "updated_at": now,
        "history": [{"at": now, "actor": author or "anonymous", "action": "created"}],
    }
    data["requests"].append(req)
    data["next_seq"] = seq + 1
    _write(data)
    return req


def set_status(req_id: str, status: str, actor: str) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    data = _read()
    for r in data["requests"]:
        if r.get("id") == req_id:
            if r.get("status") == status:
                return r  # no-op, keep history clean
            r["status"] = status
            r["updated_at"] = _now()
            r.setdefault("history", []).append(
                {"at": _now(), "actor": actor or "admin", "action": f"status → {status}"}
            )
            _write(data)
            return r
    return None


def mark_done_by_ref(req_id: str, commit_sha: str, commit_url: str | None = None) -> dict | None:
    """Mark a request done from a git push (webhook). Idempotent: re-marking an
    already-done request just records the extra commit reference, never errors."""
    data = _read()
    for r in data["requests"]:
        if r.get("id") == req_id:
            note = f"closed by commit {commit_sha}" + (f" ({commit_url})" if commit_url else "")
            already_done = r.get("status") == "done"
            if not already_done:
                r["status"] = "done"
                r["updated_at"] = _now()
            r.setdefault("history", []).append(
                {"at": _now(), "actor": "github", "action": note}
            )
            _write(data)
            return r
    return None
