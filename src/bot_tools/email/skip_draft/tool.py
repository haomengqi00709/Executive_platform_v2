IS_ACTION = True


def build(ctx):
    def skip_draft() -> str:
        state = ctx.state
        draft = state.get("pending_draft")
        if not draft:
            return "No pending draft to skip."
        queue      = list(state.get("pending_queue") or [])
        next_draft = queue[0] if queue else None
        state["pending_draft"] = next_draft
        state["pending_queue"] = queue[1:] if queue else []
        print(f"[Bot] skip_draft → '{draft.get('subject')}'")
        nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
        return f"Skipped: '{draft.get('subject')}'{nxt}"
    return skip_draft
