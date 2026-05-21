"""
External event injection into the bot's LangGraph state.

event_type options:
  "expense_pending" — sets pending_expense + pending_state="expense"
  "meeting_drafts"  — appends to pending_meeting_drafts + pending_state="meeting"
  "digest_update"   — updates digest_emails list
  "draft_prompt"    — sets draft_select_emails + pending_state="draft_select"
"""
from __future__ import annotations


def inject_event(user_id: str, chat_id: str, event_type: str, payload) -> bool:
    if not chat_id:
        return False
    try:
        from src.bot.state import get_app
        app    = get_app(user_id)
        config = {"configurable": {"thread_id": chat_id}}

        if event_type == "expense_pending":
            app.update_state(config, {"pending_expense": payload, "pending_state": "expense"})

        elif event_type == "meeting_drafts":
            snapshot = app.get_state(config)
            existing = (snapshot.values or {}).get("pending_meeting_drafts") or []
            new_list = existing + (payload if isinstance(payload, list) else [payload])
            app.update_state(config, {"pending_meeting_drafts": new_list, "pending_state": "meeting"})

        elif event_type == "digest_update":
            app.update_state(config, {"digest_emails": payload})

        elif event_type == "draft_prompt":
            app.update_state(config, {"draft_select_emails": payload, "pending_state": "draft_select"})

        else:
            print(f"[BotEvents] Unknown event_type: {event_type!r}")
            return False

        print(f"[BotEvents] Injected '{event_type}' for user {user_id[:8]}")
        return True
    except Exception as e:
        print(f"[BotEvents] inject_event failed ({event_type}): {e}")
        return False
