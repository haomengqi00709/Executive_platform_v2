IS_ACTION = True


def build(ctx):
    def dismiss_email_followup(from_name_or_subject: str) -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        monitor_path = data_dir / "email_monitor.json"
        if not monitor_path.exists():
            return "No email monitor state found."
        try:
            import json as _j
            monitor = _j.loads(monitor_path.read_text())
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
            monitor_path.write_text(_j.dumps(monitor, indent=2, ensure_ascii=False))
            return f"✅ Removed {removed} follow-up reminder(s) matching '{from_name_or_subject}'."
        except Exception as e:
            return f"Error: {e}"
    return dismiss_email_followup
