IS_ACTION = True


def build(ctx):
    def mark_commitment_done(index_or_hint: str) -> str:
        from src.modules import commitments_store as store
        from src.bot_tools.commitments._shared import resolve_ref
        data_dir = ctx.data_dir
        if index_or_hint.strip().lower() == "all":
            asked_ids = store.get_asked_ids(data_dir)
            for cid in asked_ids:
                store.mark_done(data_dir, cid, method="user")
            print(f"[Bot] mark_commitment_done(all) → {len(asked_ids)} items")
            return f"✅ Marked {len(asked_ids)} commitments as done."
        import re
        arg = index_or_hint.strip()
        nums = re.findall(r"\d+", arg)
        if len(nums) >= 2 and re.fullmatch(r"[\d\s,]*(?:and\s*[\d\s,]*)*", arg.lower()):
            done = []
            for t in nums:
                cid, desc = resolve_ref(ctx, data_dir, t)
                if cid:
                    store.mark_done(data_dir, cid, method="user")
                    done.append(desc)
            if not done:
                return (f"⚠️ I can't match '{index_or_hint}' to commitments on your current list — "
                        f"show the list and ask which; do NOT claim they're done.")
            print(f"[Bot] mark_commitment_done({nums})")
            return "✅ Done: " + "; ".join(f'"{d}"' for d in done)
        cid, desc = resolve_ref(ctx, data_dir, index_or_hint)
        if not cid:
            return (f"⚠️ I can't match '{index_or_hint}' to a commitment on your current list — "
                    f"tell the user that honestly and show the list; do NOT claim it's done or ask them to refresh.")
        store.mark_done(data_dir, cid, method="user")
        print(f"[Bot] mark_commitment_done({index_or_hint!r}) → {cid}")
        return f"✅ Done: \"{desc}\""
    return mark_commitment_done
