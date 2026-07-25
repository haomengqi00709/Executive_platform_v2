IS_ACTION = True


def build(ctx):
    def confirm_group_email() -> str:
        from src.bot import _notify_owner
        pending = ctx.state.get("pending_group_email")
        if not pending:
            return "There's no group email staged right now."
        owner_uid = ctx.state.get("owner_uid", "")
        tag    = pending.get("tag", "")
        intent = pending.get("intent", "")
        cnote  = pending.get("context_note", "")
        emails = list(pending.get("emails") or [])
        ctx.state["pending_group_email"] = None
        if not emails:
            return "That staged group email had no recipients — cleared it."

        _settings = ctx.settings
        _data_dir = ctx.data_dir
        _owner_graph = ctx.owner_graph

        def _run():
            try:
                from src.modules.outreach import generate_bulk, commit_bulk
                from src.ai import AIClient
                ai = AIClient(settings=_settings)
                preview = generate_bulk(
                    ai=ai, data_dir=_data_dir, settings=_settings,
                    emails=emails, subject="", body=intent,
                    personalize=True, context_note=cnote, write_files=False,
                )
                items = preview.get("items", [])
                # Fresh token/GraphClient INSIDE the thread — the closure's
                # owner_graph token can expire before a big batch finishes.
                if owner_uid:
                    from src import auth
                    from src.graph import GraphClient
                    graph = GraphClient(auth.get_valid_access_token(owner_uid))
                else:
                    graph = _owner_graph
                result = commit_bulk(
                    graph=graph, data_dir=_data_dir, settings=_settings,
                    items=items, send=False, write_files=False,
                )
                n    = result.get("summary", {}).get("drafts", 0)
                errs = result.get("summary", {}).get("errors", 0)
                msg = (f"✅ {n} draft{'s' if n != 1 else ''} for '{tag}' are in your "
                       f"Outlook Drafts — review and send each from there.")
                if errs:
                    msg += f" ({errs} couldn't be created.)"
                _notify_owner(owner_uid, msg)
            except Exception as e:
                print(f"[Bot] confirm_group_email error: {e}")
                _notify_owner(owner_uid, f"I hit an error drafting the '{tag}' group email: {e}")

        import threading
        threading.Thread(target=_run, daemon=True).start()
        n = len(emails)
        return (f"Drafting {n} personalized email{'s' if n != 1 else ''} for '{tag}' in the "
                f"background — I'll ping you here when they're in your Drafts.")
    return confirm_group_email
