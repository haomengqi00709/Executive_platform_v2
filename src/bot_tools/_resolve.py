"""Shared '#N / id / keyword' → record resolver for every list-returning domain.

The matching that turns "the number the user saw" into "the exact record" must happen in CODE, not
by letting the model guess a name (the "I couldn't find 'Commercial Rates'" bug). commitments and
projects each grew their own near-identical resolver; this is the one both (and email) can share.

`resolve_in_list(hint, ordered_items, ...)` returns ONE item dict from `ordered_items` (which the
caller has already put in the SAME order the user was shown — e.g. via _section_display_order, so a
"#N" from a pushed briefing lines up). It never guesses on ambiguity.
  digit   → the snapshot of what the user saw (ctx.state['_shown_lists'][bucket], optionally
            source-guarded) mapped back into ordered_items by id; else positional into ordered_items.
  non-digit → exact id/alias → contiguous substring → token-subset (≥2 words, ambiguous → None).
"""
import re


def _shown_snapshot(ctx, bucket, require_source=None):
    snap = (((getattr(ctx, "state", None) or {}).get("_shown_lists") or {}).get(bucket) or {})
    if require_source and snap.get("source") != require_source:
        return {}
    return snap


def resolve_in_list(hint, ordered_items, *, ctx=None, bucket=None, require_source=None,
                    id_field="id", id_aliases=(), keyword_fields=None, token_subset=True):
    """Resolve a reference to ONE item dict, or None. See module docstring.

    ctx/bucket enable the registry snapshot (the exact list the user saw); require_source guards a
    SHARED bucket (e.g. 'emails' is reused by reply_needed/followup/recent) so a "#2" can't bind to
    a different list. id_aliases are extra exact-match id fields (e.g. ('email_id',)). keyword_fields
    are the fields substring/token-subset run over (default: just id_field's sibling label is the
    caller's job — pass them explicitly)."""
    s = (hint or "").strip()
    if not s:
        return None
    id_keys = (id_field,) + tuple(id_aliases)
    kw_fields = tuple(keyword_fields or ())

    if s.isdigit():
        pos = int(s)
        snap = _shown_snapshot(ctx, bucket, require_source) if (ctx is not None and bucket) else {}
        for row in snap.get("items") or []:
            if row.get("pos") == pos and row.get("id"):
                for it in ordered_items:
                    if any(it.get(k) == row["id"] for k in id_keys):
                        return it
                # snapshot pointed at a row no longer visible (e.g. already dismissed) — fall through
                break
        if 1 <= pos <= len(ordered_items):
            return ordered_items[pos - 1]
        return None

    for it in ordered_items:                                    # exact id / alias
        if any((it.get(k) or "") == s for k in id_keys):
            return it

    low = s.lower()
    for it in ordered_items:                                    # contiguous substring (most precise)
        hay = " ".join((it.get(f) or "") for f in kw_fields).lower()
        if low and low in hay:
            return it

    if token_subset:                                            # compressed ref ("Daniel MEP")
        words = [w for w in re.split(r"\W+", low) if len(w) >= 2]
        if len(words) >= 2:
            best = None
            for it in ordered_items:
                hay = " ".join((it.get(f) or "") for f in kw_fields).lower().replace("-", " ")
                hay_words = set(re.split(r"\W+", hay))
                if all(w in hay_words for w in words):
                    if best is not None:
                        return None                            # ambiguous — never guess
                    best = it
            if best is not None:
                return best
    return None
