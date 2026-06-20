IS_ACTION = True


def build(ctx):
    def mark_commitment_done(index_or_hint: str) -> str:
        from src.modules.commitments_state import mark_done as _mark_done, load_state as _load_state
        from src.bot_tools.commitments._shared import resolve_commitment
        data_dir = ctx.data_dir
        if index_or_hint.strip().lower() == "all":
            st = _load_state(data_dir)
            asked_ids = list(st.get("asked", {}).keys())
            for cid in asked_ids:
                _mark_done(data_dir, cid, method="user")
            print(f"[Bot] mark_commitment_done(all) → {len(asked_ids)} items")
            return f"✅ Marked {len(asked_ids)} commitments as done."
        cid, desc = resolve_commitment(data_dir, index_or_hint)
        if not cid:
            return f"⚠️ Couldn't find commitment '{index_or_hint}'. Run commitments_extract first."
        _mark_done(data_dir, cid, method="user")
        print(f"[Bot] mark_commitment_done({index_or_hint!r}) → {cid}")
        return f"✅ Done: \"{desc}\""
    return mark_commitment_done
