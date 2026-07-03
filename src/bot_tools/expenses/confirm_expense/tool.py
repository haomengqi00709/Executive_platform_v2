IS_ACTION = True


def build(ctx):
    def confirm_expense() -> str:
        pending = ctx.state.get("pending_expense")
        item = (pending or {}).get("item")
        if not item:
            return "No pending expense to confirm."
        try:
            from src.modules import expenses_store
            expenses_store.upsert_expense(ctx.data_dir, item)
            # Record the file hash (the json cache the Teams handler reads) so a re-send is caught.
            h = pending.get("hash")
            hashes_file = pending.get("hashes_file")
            if h and hashes_file and not pending.get("is_hash_dup"):
                from pathlib import Path as _Path
                from src.modules.m05_expense import _load_hashes, _save_hashes
                hf = _Path(hashes_file)
                hashes = _load_hashes(hf)
                hashes[h] = {"filename": item.get("attachment", ""), "vendor": item.get("vendor", ""),
                             "amount": item.get("amount", ""), "currency": item.get("currency", "CAD"),
                             "date": item.get("date", ""), "category": item.get("category", "Other"),
                             "processed_date": item.get("processed_at", "")}
                _save_hashes(hashes, hf)
            ctx.state["pending_expense"] = None
            return f"✅ {str(item.get('document_type', 'receipt')).capitalize()} recorded as a new entry."
        except Exception as e:
            return f"Error confirming expense: {e}"
    return confirm_expense
