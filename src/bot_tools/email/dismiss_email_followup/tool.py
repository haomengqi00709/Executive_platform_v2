import re

IS_ACTION = True


def _hay(it):
    return " ".join((it.get(f) or "") for f in ("to_name", "to_email", "subject")).lower()


def _match_by_text(items, q):
    """Name/subject hint dismisses ALL matching follow-ups: contiguous substring first (precise), then
    token-subset (every ≥2-char hint word appears in name/email/subject) — for compressed refs."""
    matched = [it for it in items if q in _hay(it)]
    if not matched:
        words = [w for w in re.split(r"\W+", q) if len(w) >= 2]
        if len(words) >= 2:
            matched = [it for it in items if all(w in set(re.split(r"\W+", _hay(it))) for w in words)]
    return matched


def _render(items):
    return "; ".join(
        f'[#{i + 1}] "{(it.get("to_name") or it.get("to_email") or "")}" — {(it.get("subject") or "")[:40]}'
        for i, it in enumerate(items[:6]))


def build(ctx):
    def dismiss_email_followup(from_name_or_subject: str) -> str:
        from src.modules import email_store
        from src.bot_tools.email._shared import visible_followups, resolve_followup
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            items = visible_followups(ctx)
            if not items:
                return "You have no follow-ups currently awaiting a reply — nothing to close."

            q = (from_name_or_subject or "").lower().strip()
            tokens = [t.strip() for t in q.replace(",", " ").split() if t.strip()]
            missing = []

            if q in ("all", "those", "them", "these", "all of them", "everything", ""):
                matched = list(items)                          # "close those / all" → every open follow-up
            elif tokens and all(t.isdigit() for t in tokens):
                # position(s) — "1", "1,3", "2 3" — resolved in CODE the way the user saw the list
                # (snapshot or canonical display order), never by guessing a name from the number.
                matched = []
                for t in tokens:
                    it = resolve_followup(ctx, t, ordered_items=items)
                    if it is not None and it not in matched:
                        matched.append(it)
                    else:
                        missing.append(t)
                if not matched:
                    return (f"⚠️ #{', #'.join(tokens)} doesn't line up with your follow-up list "
                            f"({len(items)} open): {_render(items)}. Which number? Don't claim it's dismissed.")
            else:
                matched = _match_by_text(items, q)
                if not matched:
                    return (f"⚠️ I can't match '{from_name_or_subject}' to a follow-up you're awaiting. "
                            f"Your open follow-ups: {_render(items)}. Which one (or say 'all')? "
                            f"Don't claim it's dismissed.")

            for it in matched:
                # Carry the pointer (email_id / conversation_id) so the annotation stays navigable
                # back to the original sent email (open_email).
                email_store.mark_handled(
                    data_dir, counterparty=it.get("to_email", ""), subject=it.get("subject", ""),
                    kind="followup_dismissed", source="dismiss_followup",
                    email_id=it.get("email_id", ""), conversation_id=it.get("conversation_id", ""))
            who = ", ".join(sorted({(it.get("to_name") or it.get("to_email") or "") for it in matched}))
            print(f"[Bot] dismiss_email_followup('{from_name_or_subject}') → {len(matched)} followup(s)")
            note = f" (couldn't find #{', #'.join(missing)})" if missing else ""
            return (f"✅ Dismissed {len(matched)} follow-up(s) ({who}){note} — "
                    f"won't flag them as awaiting a reply again.")
        except Exception as e:
            return f"Error: {e}"
    return dismiss_email_followup
