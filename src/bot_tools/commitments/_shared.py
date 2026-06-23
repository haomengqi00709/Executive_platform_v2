"""Shared helper for the commitment tools — resolves against the live store."""
from src.modules import commitments_store as store


def resolve_ref(ctx, data_dir, index_or_hint: str):
    """Resolve a commitment the way the USER saw it (registry-aware).

    A bare position ("2") means "the 2nd item in the list the bot just showed", NOT the 2nd
    row of the store. So for a bare integer we map it through what was actually shown:
      1. ctx.state['_shown_lists']['commitments'] — the exact list/order the user saw;
      2. else the canonical DISPLAY order (_section_display_order over the live store).
    ids and keywords fall through to resolve_commitment (which reads the live store).
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
            ordered = _section_display_order(
                "commitments_extract", {"items": store.query_visible(data_dir)})
            if 1 <= pos <= len(ordered):
                return ordered[pos - 1].get("id"), ordered[pos - 1].get("description", "")
        except Exception:
            pass
    return resolve_commitment(data_dir, s)


def resolve_commitment(data_dir, index_or_hint: str):
    """Return (commitment_id, description) for the referenced commitment, from the LIVE store.

    Order: exact id/email_id → 1-based positional → keyword substring. Reading the store
    (query_visible) means resolution always reflects current state (done/snoozed excluded).
    """
    try:
        items = store.query_visible(data_dir)
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
