import json

IS_ACTION = False


def build(ctx):
    def list_pending_drafts() -> str:
        from src.bot import _with_indices
        state = ctx.state
        queue   = list(state.get("pending_queue") or [])
        current = state.get("pending_draft")
        if not current and not queue:
            return json.dumps({"pending": [], "note": "No pending drafts."}, ensure_ascii=False)

        def _shape(d: dict, is_current: bool) -> dict:
            return {
                "to":         d.get("to", ""),
                "subject":    d.get("subject", ""),
                "body":       (d.get("body") or "")[:400],
                "is_current": is_current,
            }

        items = []
        if current:
            items.append(_shape(current, True))
        for d in queue:
            items.append(_shape(d, False))
        return json.dumps({"pending": _with_indices(items)}, ensure_ascii=False)
    return list_pending_drafts
