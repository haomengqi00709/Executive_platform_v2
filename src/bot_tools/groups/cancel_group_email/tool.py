IS_ACTION = True


def build(ctx):
    def cancel_group_email() -> str:
        state = ctx.state
        if not state.get("pending_group_email"):
            return "There's no group email staged to cancel."
        tag = (state.get("pending_group_email") or {}).get("tag", "")
        state["pending_group_email"] = None
        return f"Cancelled the group email{f' to {tag}' if tag else ''}."
    return cancel_group_email
