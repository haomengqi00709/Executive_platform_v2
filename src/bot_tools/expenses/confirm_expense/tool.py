IS_ACTION = True


def build(ctx):
    def confirm_expense() -> str:
        pending = ctx.state.get("pending_expense")
        if not pending:
            return "No pending expense to confirm."
        try:
            import openpyxl
            from pathlib import Path as _Path
            master_file  = _Path(pending["master_file"])
            expenses_dir = _Path(pending["expenses_dir"])
            hashes_file  = _Path(pending["hashes_file"]) if pending.get("hashes_file") else None

            expenses_dir.mkdir(parents=True, exist_ok=True)
            from src.modules.m05_expense import _append_row, _init_workbook, _load_hashes, _save_hashes
            wb = openpyxl.load_workbook(master_file) if master_file.exists() else _init_workbook()
            _append_row(wb.active, pending["new_row"])
            wb.save(master_file)
            if hashes_file and pending.get("hash") and not pending.get("is_hash_dup"):
                hashes = _load_hashes(hashes_file)
                hashes[pending["hash"]] = pending["new_row"].get("Attachment", "")
                _save_hashes(hashes, hashes_file)
            ctx.state["pending_expense"] = None
            return "✅ Expense recorded as a new entry."
        except Exception as e:
            return f"Error confirming expense: {e}"
    return confirm_expense
