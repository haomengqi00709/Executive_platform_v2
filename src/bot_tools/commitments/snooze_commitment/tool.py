IS_ACTION = True


def build(ctx):
    def snooze_commitment(index_or_hint: str, days: int = 3) -> str:
        from src.modules.commitments_state import mark_snoozed as _mark_snoozed
        from src.bot_tools.commitments._shared import resolve_ref
        from datetime import date, timedelta
        data_dir = ctx.data_dir
        tokens = [t.strip() for t in index_or_hint.replace(",", " ").split() if t.strip()]
        if len(tokens) > 1 and all(t.isdigit() for t in tokens):
            snoozed = []
            for t in tokens:
                cid, desc = resolve_ref(ctx, data_dir, t)
                if cid:
                    _mark_snoozed(data_dir, cid, days=days)
                    snoozed.append(desc)
            if not snoozed:
                return f"⚠️ I can't match '{index_or_hint}' to commitments on your current list — show the list and ask which; don't claim it's snoozed."
            until = (date.today() + timedelta(days=days)).strftime("%B %d")
            print(f"[Bot] snooze_commitment({tokens}, {days}d)")
            return f"⏰ Snoozed {len(snoozed)} commitments until {until}."
        cid, desc = resolve_ref(ctx, data_dir, index_or_hint)
        if not cid:
            return f"⚠️ I can't match '{index_or_hint}' to a commitment on your current list — show the list and ask which; don't claim it's snoozed."
        _mark_snoozed(data_dir, cid, days=days)
        print(f"[Bot] snooze_commitment({index_or_hint!r}, {days}d) → {cid}")
        until = (date.today() + timedelta(days=days)).strftime("%B %d")
        return f"⏰ Snoozed until {until}: \"{desc}\""
    return snooze_commitment
