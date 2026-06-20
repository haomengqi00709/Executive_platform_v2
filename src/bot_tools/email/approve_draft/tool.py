IS_ACTION = True


def build(ctx):
    def approve_draft() -> str:
        from src.modules.profile import append_signature_to_body, get_user_signature
        state = ctx.state
        draft = state.get("pending_draft")
        if not draft:
            return "No pending draft to approve."
        if ctx.owner_graph is None:
            return "Owner account not available."
        try:
            final_body = append_signature_to_body(draft.get("body", ""), get_user_signature(ctx.settings))
            result = ctx.owner_graph.create_draft(
                to      = draft.get("to", ""),
                subject = draft.get("subject", ""),
                body    = final_body,
            )
            queue      = list(state.get("pending_queue") or [])
            next_draft = queue[0] if queue else None
            state["pending_draft"] = next_draft
            state["pending_queue"] = queue[1:] if queue else []
            print(f"[Bot] approve_draft → '{draft.get('subject')}'")
            web_link = result.get("webLink", "")
            nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
            if web_link:
                from src.modules.links import wrap_draft_link
                return f"✅ Draft saved — <a href='{wrap_draft_link(web_link)}'>Open in Outlook to review and send</a>{nxt}"
            return f"✅ Draft saved to Outlook Drafts: '{draft.get('subject')}'{nxt}"
        except Exception as e:
            return f"Error saving draft: {e}"
    return approve_draft
