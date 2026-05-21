"""
BotState schema + per-user app factory.

SqliteSaver persists conversation state to .data/{user_id}/bot.sqlite — survives restarts.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver

from src import auth


class BotState(TypedDict):
    # ── Per-turn (reset each invoke) ──────────────────────────
    text:    str
    sender:  str
    intent:  Optional[str]
    reply:   Optional[str]

    # ── Persistent (carried across turns via SqliteSaver) ─────
    pending_state:          str
    pending_draft:          Optional[dict]
    pending_expense:        Optional[dict]
    pending_meeting_drafts: list
    pending_queue:          list
    pending_config_update:  Optional[dict]
    chat_history:           list
    digest_emails:          list
    draft_select_emails:    list


_cache: dict[str, object] = {}
_cache_lock = threading.Lock()


def get_app(user_id: str):
    with _cache_lock:
        if user_id not in _cache:
            import sqlite3
            db_path = auth.DATA_DIR / user_id / "bot.sqlite"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            checkpointer = SqliteSaver(conn)
            from src.bot.graph import build_graph
            _cache[user_id] = build_graph(checkpointer)
        return _cache[user_id]


def get_thread_config(chat_id: str, graph_client, ai,
                      owner_graph=None, owner_wiki_dir=None,
                      owner_settings=None, owner_settings_path=None,
                      owner_context_path=None, owner_data_dir=None,
                      bot_state_path=None) -> dict:
    return {
        "configurable": {
            "thread_id":           chat_id,
            "chat_id":             chat_id,
            "graph_client":        graph_client,
            "ai":                  ai,
            "owner_graph":         owner_graph,
            "owner_wiki_dir":      owner_wiki_dir,
            "owner_settings":      owner_settings or {},
            "owner_settings_path": owner_settings_path,
            "owner_context_path":  owner_context_path,
            "owner_data_dir":      owner_data_dir,
            "bot_state_path":      bot_state_path,
        }
    }


def invalidate_cache(user_id: str):
    with _cache_lock:
        _cache.pop(user_id, None)
