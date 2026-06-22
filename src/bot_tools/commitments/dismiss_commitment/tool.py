IS_ACTION = True


def build(ctx):
    def dismiss_commitment(index_or_hint: str) -> str:
        from src.modules.commitments_state import mark_done as _mark_done, load_state as _load_state
        from src.bot_tools.commitments._shared import resolve_ref
        data_dir = ctx.data_dir
        if index_or_hint.strip().lower() == "all":
            st = _load_state(data_dir)
            asked_ids = list(st.get("asked", {}).keys())
            for cid in asked_ids:
                _mark_done(data_dir, cid, method="user_dismissed")
            return f"✅ Dismissed {len(asked_ids)} commitments."
        tokens = [t.strip() for t in index_or_hint.replace(",", " ").split() if t.strip()]
        if len(tokens) > 1 and all(t.isdigit() for t in tokens):
            dismissed = []
            for t in tokens:
                cid, desc = resolve_ref(ctx, data_dir, t)
                if cid:
                    _mark_done(data_dir, cid, method="user_dismissed")
                    dismissed.append(desc)
            if not dismissed:
                return f"⚠️ I can't match '{index_or_hint}' to commitments on your current list — show the list and ask which; don't claim it's dismissed."
            print(f"[Bot] dismiss_commitment({tokens})")
            return f"🗑️ Skipped {len(dismissed)} commitments."
        cid, desc = resolve_ref(ctx, data_dir, index_or_hint)
        if not cid:
            return f"⚠️ I can't match '{index_or_hint}' to a commitment on your current list — show the list and ask which; don't claim it's dismissed."
        _mark_done(data_dir, cid, method="user_dismissed")
        print(f"[Bot] dismiss_commitment({index_or_hint!r}) → {cid}")
        return f"🗑️ Skipped: \"{desc}\""
    return dismiss_commitment
