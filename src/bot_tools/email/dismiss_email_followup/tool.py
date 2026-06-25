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
            # Apply the read-time overlay so already-dismissed items aren't "matched" again.
            try:
                kept, _ = email_store.overlay_handled(
                    data_dir, items, kinds=email_store.FOLLOWUP_KINDS, key_field="to_email")
                items = kept
            except Exception:
                pass
            if not items:
                return ("You have no follow-ups currently awaiting a reply — nothing to close.")

            q = from_name_or_subject.lower().strip()

            def _hay(it):
                return " ".join((it.get(f) or "") for f in ("to_name", "to_email", "subject")).lower()

            if q in ("all", "those", "them", "these", "all of them", "everything", ""):
                matched = list(items)                      # "close those / all" → every open follow-up
            else:
                matched = [it for it in items if q in _hay(it)]    # contiguous substring (precise)
                if not matched:
                    # Token-subset: the model often passes a name/subject that isn't a contiguous
                    # substring ("Daniel MEP" vs "Daniel — MEP Ai Tools"). Match when every hint word
                    # (≥2 words) appears somewhere in name/email/subject. This is Daniel's reported
                    # "names/subjects didn't precisely match" failure.
                    import re
                    words = [w for w in re.split(r"\W+", q) if len(w) >= 2]
                    if len(words) >= 2:
                        matched = [it for it in items
                                   if all(w in set(re.split(r"\W+", _hay(it))) for w in words)]
            if not matched:
                shown = "; ".join(f'"{(it.get("to_name") or it.get("to_email") or "")}" — '
                                  f'{(it.get("subject") or "")[:40]}' for it in items[:6])
                return (f"⚠️ I can't match '{from_name_or_subject}' to a follow-up you're awaiting. "
                        f"Your open follow-ups: {shown}. Which one (or say 'all')? Don't claim it's dismissed.")
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
