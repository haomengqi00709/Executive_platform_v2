IS_ACTION = True


def build(ctx):
    def dismiss_email_followup(from_name_or_subject: str) -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            import json as _j
            from src.modules import email_store
            # The follow-ups the user sees come from the followup_needed section (emails THEY sent
            # that haven't been answered). Resolve the hint against that LIVE list, then record a
            # durable 'followup_dismissed' annotation so the item drops off and stays off (read-time
            # overlay in read_module_result/followup_needed honours it).
            # (Was: grepped the long-dead `pending_priority_followup` list — always empty since the
            #  reply_needed=single-source refactor — so it always returned "no match".)
            path = data_dir / "results" / "followup_needed.json"
            items = (_j.loads(path.read_text()).get("items") if path.exists() else []) or []
            q = from_name_or_subject.lower().strip()
            matched = [it for it in items
                       if q in (it.get("to_name") or "").lower()
                       or q in (it.get("to_email") or "").lower()
                       or q in (it.get("subject") or "").lower()]
            if not matched:
                return (f"⚠️ I can't find a follow-up to '{from_name_or_subject}' in your current "
                        f"'awaiting reply' list — show the list and ask which; don't claim it's dismissed.")
            for it in matched:
                # Carry the pointer (email_id/conversation_id) so the annotation can be navigated
                # back to the original sent email (open_email) — followup_needed items have them.
                email_store.mark_handled(
                    data_dir, counterparty=it.get("to_email", ""), subject=it.get("subject", ""),
                    kind="followup_dismissed", source="dismiss_followup",
                    email_id=it.get("email_id", ""), conversation_id=it.get("conversation_id", ""))
            who = ", ".join(sorted({(it.get("to_name") or it.get("to_email") or "") for it in matched}))
            print(f"[Bot] dismiss_email_followup('{from_name_or_subject}') → {len(matched)} followup(s)")
            return f"✅ Dismissed {len(matched)} follow-up(s) ({who}) — won't flag them as awaiting a reply again."
        except Exception as e:
            return f"Error: {e}"
    return dismiss_email_followup
