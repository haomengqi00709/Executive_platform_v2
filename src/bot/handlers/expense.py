"""
Expense handler — receipt confirmation flow.

Intents: expense_yes, expense_no, expense_wait
expense_wait: ambiguous reply while expense pending — re-ask.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def _confirm(pending: dict) -> None:
    """Write confirmed field-duplicate receipt into expense Excel."""
    import openpyxl
    from pathlib import Path
    from src.modules.m05_expense import (
        _append_row, _init_workbook, _load_hashes, _save_hashes,
    )
    master_file  = Path(pending["master_file"])
    expenses_dir = Path(pending["expenses_dir"])
    hashes_file  = Path(pending["hashes_file"]) if pending.get("hashes_file") else None

    expenses_dir.mkdir(parents=True, exist_ok=True)
    if master_file.exists():
        wb = openpyxl.load_workbook(master_file)
        ws = wb.active
    else:
        from src.modules.m05_expense import _init_workbook
        wb = _init_workbook()
        ws = wb.active

    _append_row(ws, pending["new_row"])
    wb.save(master_file)

    hashes = _load_hashes(hashes_file)
    hashes[pending["hash"]] = pending["new_row"].get("Attachment", "")
    _save_hashes(hashes, hashes_file)
    print(f"[Expense] Confirmed duplicate — recorded {pending['new_row'].get('Vendor','?')}")


def expense_node(state: BotState, config: RunnableConfig) -> dict:
    intent  = state.get("intent")
    pending = state.get("pending_expense")

    if intent == "expense_yes":
        try:
            _confirm(pending)
            reply = "✅ Recorded as a new expense."
        except Exception as e:
            reply = f"❌ Failed to record expense: {e}"
        return {"reply": reply, "pending_expense": None, "pending_state": "idle"}

    if intent == "expense_no":
        return {"reply": "🗑️ Discarded — not recorded.", "pending_expense": None, "pending_state": "idle"}

    # expense_wait — user said something unrelated; re-ask
    vendor = (pending or {}).get("new_row", {}).get("Vendor", "?")
    return {
        "reply": (
            f"Still waiting on the duplicate receipt confirmation ({vendor}).\n"
            "Reply YES to record as a new expense, or NO to discard."
        )
    }
