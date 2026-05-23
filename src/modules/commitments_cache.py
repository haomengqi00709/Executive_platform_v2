"""
commitments_cache — incremental extraction cache for commitments_extract.

Cache file: data_dir/commitments_cache.json
  last_processed: ISO timestamp of the newest email processed
  emails: { email_id → { received, extracted_at, commitments: [raw AI results] } }

Entries older than 30 days are auto-pruned on each run.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FILENAME = "commitments_cache.json"
_PRUNE_DAYS = 30


def load_cache(data_dir: Path) -> dict:
    path = Path(data_dir) / _FILENAME
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def save_cache(data_dir: Path, cache: dict) -> None:
    path = Path(data_dir) / _FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    tmp.replace(path)


def prune_cache(cache: dict, days: int = _PRUNE_DAYS) -> int:
    """Remove email entries older than N days. Returns count pruned."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    emails = cache.get("emails", {})
    stale = [eid for eid, entry in emails.items() if (entry.get("received") or "") < cutoff]
    for eid in stale:
        del emails[eid]
    cache["emails"] = emails
    return len(stale)


def get_last_processed(cache: dict) -> str:
    """Return ISO timestamp of last processed email, or '' if cache is empty."""
    return cache.get("last_processed", "")


def _extract_msg_meta(msg: dict) -> dict:
    """Extract the minimal fields needed to reconstruct sender/subject for dedup and display."""
    return {
        "id":                msg.get("id", ""),
        "subject":           msg.get("subject", ""),
        "receivedDateTime":  msg.get("receivedDateTime", ""),
        "bodyPreview":       (msg.get("bodyPreview") or "")[:300],
        "from":              msg.get("from", {}),
    }


def add_email_result(
    cache: dict,
    email_id: str,
    received: str,
    raw_commitments: list,
    msg: dict = None,
) -> None:
    """Store AI extraction result for one email. Pass msg to persist sender/subject metadata."""
    cache.setdefault("emails", {})
    entry: dict = {
        "received":     received,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "commitments":  raw_commitments,
    }
    if msg:
        entry["msg_meta"] = _extract_msg_meta(msg)
    cache["emails"][email_id] = entry
    current = cache.get("last_processed", "")
    if received > current:
        cache["last_processed"] = received


def flatten_commitments(cache: dict, msg_index: dict) -> list[dict]:
    """
    Flatten all cached email entries into a list of (raw_commitment, msg) pairs.
    msg_index: { email_id → full Graph API message dict } — used for emails fetched this run.
    Falls back to cached msg_meta for older emails not in msg_index.
    """
    result = []
    for email_id, entry in cache.get("emails", {}).items():
        msg = msg_index.get(email_id) or entry.get("msg_meta") or {}
        for raw_c in entry.get("commitments", []):
            result.append({
                "_email_id": email_id,
                "_received": entry.get("received", ""),
                "_msg":      msg,
                **raw_c,
            })
    return result
