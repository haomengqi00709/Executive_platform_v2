"""Shared helpers for the email follow-up tools — resolve a reference the way the USER saw the list.

The follow-up list the user acts on is followup_needed (emails THEY sent, awaiting a reply). We build
it in the SAME order the briefing/read shows it, then resolve "#N / name / 1,3" against that list IN
CODE (src/bot_tools/_resolve.resolve_in_list) — the model never turns a number into a guessed name.
The 'emails' #N bucket is shared (reply_needed/recent also use it), so the snapshot is source-guarded
to 'followup_needed'.
"""
import json

from src.modules import email_store
from src.bot_tools._resolve import resolve_in_list


def visible_followups(ctx) -> list:
    """The live follow-up list exactly as the user sees it: followup_needed.json items, already-dismissed
    ones overlaid out, ordered the same way the briefing / read_module_result orders them."""
    data_dir = getattr(ctx, "data_dir", None)
    if not data_dir:
        return []
    path = data_dir / "results" / "followup_needed.json"
    if not path.exists():
        return []
    try:
        items = (json.loads(path.read_text()).get("items")) or []
    except Exception:
        return []
    try:
        kept, _ = email_store.overlay_handled(
            data_dir, items, kinds=email_store.FOLLOWUP_KINDS, key_field="to_email")
        items = kept
    except Exception:
        pass
    try:
        from src.server import _section_display_order
        from zoneinfo import ZoneInfo
        tzname = (getattr(ctx, "settings", None) or {}).get("timezone") or "UTC"
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            tz = ZoneInfo("UTC")
        items = _section_display_order("followup_needed", {"items": items}, tz)
    except Exception:
        pass
    return items


def resolve_followup(ctx, hint: str, ordered_items=None):
    """Resolve one follow-up reference (position / name / subject) to its item dict, or None.
    Pass ordered_items to resolve several refs against one consistent snapshot of the list."""
    items = visible_followups(ctx) if ordered_items is None else ordered_items
    return resolve_in_list(
        hint, items, ctx=ctx, bucket="emails", require_source="followup_needed",
        id_field="email_id", keyword_fields=("to_name", "to_email", "subject"))
