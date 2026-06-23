IS_ACTION = True


def build(ctx):
    def dismiss_email_followup(from_name_or_subject: str) -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules import email_store
            # Read-modify-write through the store: atomic + serialized, so a concurrent email-poll
            # write can't corrupt the state (the old raw email_monitor.json write could).
            monitor = email_store.get_poller_state(data_dir)
            followups = monitor.get("pending_priority_followup") or []
            query = from_name_or_subject.lower()
            before = len(followups)
            remaining = [
                f for f in followups
                if query not in f.get("from_name", "").lower()
                and query not in f.get("from", "").lower()
                and query not in f.get("subject", "").lower()
            ]
            removed = before - len(remaining)
            if removed == 0:
                return f"No follow-up reminder matched '{from_name_or_subject}'."
            monitor["pending_priority_followup"] = remaining
            email_store.save_poller_state(data_dir, monitor)
            return f"✅ Removed {removed} follow-up reminder(s) matching '{from_name_or_subject}'."
        except Exception as e:
            return f"Error: {e}"
    return dismiss_email_followup
