"""Shared helper for the commitment tools."""
import json
from pathlib import Path


def resolve_ref(ctx, data_dir, index_or_hint: str):
    """Resolve a commitment the way the USER saw it (registry-aware).

    A bare position ("2") means "the 2nd item in the list the bot just showed", which
    is NOT the 2nd row of commitments_extract.json — the displayed order is date-sorted
    (_section_display_order) and differs from raw file order. Resolving a bare position
    against file order silently marks the wrong commitment (says "marked X" but marks Y).
    So for a bare integer we map it through what was actually shown:
      1. ctx.state['_shown_lists']['commitments'] — the exact list/order the user saw
         (covers cross-turn: commitments_extract / due_today / upcoming all register here).
      2. if nothing was shown this conversation, the canonical DISPLAY order
         (_section_display_order), never raw file order.
    ids and keywords fall straight through to resolve_commitment.
    """
    s = str(index_or_hint).strip()
    if s.isdigit():
        pos = int(s)
        try:
            shown = ((((getattr(ctx, "state", None) or {}).get("_shown_lists") or {})
                      .get("commitments") or {}).get("items") or [])
        except Exception:
            shown = []
        for it in shown:
            if it.get("pos") == pos and it.get("id"):
                return resolve_commitment(data_dir, it["id"])
        try:
            from src.server import _section_display_order
            data = json.loads((Path(data_dir) / "results" / "commitments_extract.json").read_text())
            ordered = _section_display_order("commitments_extract", data)
            if 1 <= pos <= len(ordered):
                return ordered[pos - 1].get("id"), ordered[pos - 1].get("description", "")
        except Exception:
            pass
    return resolve_commitment(data_dir, s)


def resolve_commitment(data_dir, index_or_hint: str):
    """Return (commitment_id, description) for the commitment the user referenced.

    Resolution order:
      1. exact canonical `id` / `email_id` — lets the bot pass the id it read off
         WHATEVER list was shown (commitments_extract / due_today / upcoming /
         a pushed briefing), so the position the user saw always maps to the right
         commitment regardless of each list's own numbering.
      2. 1-based positional index into commitments_extract.json (the legacy "mark 1"
         path). Commitment ids are 16-hex-char sha1 (see commitments_extract
         ._commitment_id), never bare ints, so step 1 can't shadow this.
      3. keyword substring match on description.
    """
    try:
        path = data_dir / "results" / "commitments_extract.json"
        if not path.exists():
            return None, ""
        data = json.loads(path.read_text())
        items = data.get("items", [])
        sval = str(index_or_hint).strip()
        if not sval:
            return None, ""
        for item in items:
            if item.get("id") == sval or item.get("email_id") == sval:
                return item["id"], item.get("description", "")
        try:
            idx = int(sval) - 1
            if 0 <= idx < len(items):
                return items[idx]["id"], items[idx].get("description", "")
        except ValueError:
            hint = sval.lower()
            for item in items:
                if hint in (item.get("description") or "").lower():
                    return item["id"], item.get("description", "")
    except Exception:
        pass
    return None, ""
