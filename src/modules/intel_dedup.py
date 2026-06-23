"""
intel_dedup — shared dedup + history tracking for the intelligence sections.

Both market_intelligence and company_intelligence used to carry identical
copies of `_load_seen` / `_save_seen` / `_dedup` / `_assign_ids` functions.
This module consolidates them and adds a second dedup layer (AI semantic
dedup at validator time) on top of the existing md5-exact layer.

Two layers of dedup:
  1. md5-exact (cheap, lossless): catches identical-headline reprints
     before the AI even sees them. Runs in filter_exact_duplicates().
  2. AI semantic (smart, bounded): the validator gets a list of
     previously-surfaced items as extra_context and removes any item
     describing the SAME news event, even if wording or source differs.
     See format_history_for_validator().

Storage format — backward-compatible upgrade:
  Old: { md5: "2026-05-26" }
  New: { md5: { headline, company, source, source_url,
                published_date, first_seen } }

  load_history() accepts both. Old bare-string entries still provide
  md5-exact dedup but are invisible to the AI validator (no headline
  text to compare). History is now kept permanently (no expiry) so the
  exact layer never re-pushes a previously-surfaced item.

Caller owns IO via load_history / save_history. Pure functions in
between — no surprise filesystem writes.
"""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path


# The md5-exact layer keeps history PERMANENTLY (see load_history) — an item that was ever
# surfaced is never re-pushed. Only the AI validator's view is bounded: feeding all historical
# headlines to the model would blow the token budget, so a story rephrased within
# _VALIDATOR_LOOKBACK days is still caught semantically; older ones rely on exact-match.
_VALIDATOR_LOOKBACK = 14


def _hash_headline(headline: str) -> str:
    """First 12 chars of md5(lowercased, stripped headline). Matches the
    legacy per-section key so old seen.json entries still hit."""
    return hashlib.md5((headline or "").lower().strip().encode()).hexdigest()[:12]


def _entry_first_seen(value) -> str:
    """Read the first_seen date from either old (bare string) or new
    (dict) schema. Returns '' if neither readable."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("first_seen") or value.get("date") or ""
    return ""


def load_history(data_dir: Path, section_id: str) -> dict:
    """Load the FULL surfaced-item history for a section — PERMANENT, no expiry.

    The md5-exact layer (filter_exact_duplicates) uses this so an item that was EVER surfaced is
    never re-pushed, even months later — it is a cheap hash-set lookup, so keeping it forever
    costs ~nothing. Only the AI validator's view is bounded (format_history_for_validator caps to
    _VALIDATOR_LOOKBACK) because feeding all historical headlines to the model would blow the token
    budget. Returns { md5_key: entry_dict_or_str }; empty dict on missing file or parse error.
    """
    path = Path(data_dir) / f"{section_id}_seen.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_history(data_dir: Path, section_id: str, history: dict) -> None:
    """Atomic write to *_seen.json (tmp + replace)."""
    path = Path(data_dir) / f"{section_id}_seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    tmp.replace(path)


def filter_exact_duplicates(
    items: list[dict], history: dict
) -> tuple[list[dict], dict]:
    """md5-exact dedup (layer 1).

    For each candidate item, compute md5(headline). If that key is
    already in history, drop the item. Otherwise add it to history
    with the rich schema and keep it.

    Returns (new_items, updated_history). Old bare-string entries in
    the history are left untouched (they expire naturally).
    """
    today = date.today().isoformat()
    new_items: list[dict] = []
    for item in items:
        headline = item.get("headline", "")
        if not headline:
            continue
        key = _hash_headline(headline)
        if key in history:
            continue
        new_items.append(item)
        history[key] = {
            "headline":       headline[:200],
            "company":        (item.get("company") or "")[:100],
            "source":         (item.get("source") or "")[:50],
            "source_url":     (item.get("source_url") or "")[:500],
            "published_date": (item.get("published_date") or "")[:10],
            "first_seen":     today,
        }
    return new_items, history


def assign_ids(items: list[dict]) -> list[dict]:
    """SHA1-based id per item. Matches the legacy per-section
    `_assign_ids` so any downstream consumer keying on item.id keeps
    working (first 16 chars of sha1 of headline)."""
    return [
        {
            **item,
            "id": hashlib.sha1((item.get("headline") or "").encode()).hexdigest()[:16],
        }
        for item in items
    ]


def format_history_for_validator(
    history: dict, lookback_days: int = _VALIDATOR_LOOKBACK
) -> str:
    """Render the history dict as a compact text block for the validator
    prompt (layer 2 — AI semantic dedup).

    Only includes rich-schema entries — skips bare-string legacy format
    (no headline text to show the AI). Sorted newest first. Caps at 200
    entries (~30 KB of prompt overhead) as a safety bound on token cost.

    Returns "" when there's nothing to show — caller then passes empty
    extra_context to the validator and behavior is identical to today.
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows: list[dict] = []
    for v in history.values():
        if not isinstance(v, dict):
            continue
        if (v.get("first_seen") or "") < cutoff:
            continue
        headline = (v.get("headline") or "").strip()
        if not headline:
            continue
        rows.append(v)
    if not rows:
        return ""
    rows.sort(key=lambda r: r.get("first_seen", ""), reverse=True)

    lines = [
        "Previously surfaced items (do NOT include any candidate item that "
        "describes the SAME news event as one of these — even if the headline "
        "wording, source, or URL differs):",
    ]
    for r in rows[:200]:
        date_part = r.get("first_seen", "")
        company   = r.get("company", "?") or "?"
        source    = r.get("source", "?") or "?"
        headline  = r.get("headline", "")[:140]
        lines.append(f"  - [{date_part}] {company} / {source}: \"{headline}\"")
    return "\n".join(lines)
