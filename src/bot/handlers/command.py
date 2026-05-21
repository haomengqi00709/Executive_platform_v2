"""
Command handler — slash commands and agent data queries.

Slash commands (/context, /settings, /help, /focus) → slash.handle()
Data queries and config updates → agent.run_command_bot()

If a draft is still pending after handling, appends a reminder.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def command_node(state: BotState, config: RunnableConfig) -> dict:
    text        = state.get("text", "").strip()
    c           = _cfg(config)
    ai          = c.get("ai")
    owner_graph = c.get("owner_graph")
    wiki_dir    = c.get("owner_wiki_dir")
    settings    = c.get("owner_settings") or {}
    settings_path = c.get("owner_settings_path")
    context_path  = c.get("owner_context_path")
    bot_state_path = c.get("bot_state_path")
    history     = state.get("chat_history") or []

    # ── Slash commands ────────────────────────────────────────────────────
    if text.startswith("/"):
        try:
            from src import slash as _slash
            reply = _slash.handle(text, context_path, settings_path, ai)
        except Exception as e:
            reply = f"❌ Command error: {e}"
        return {"reply": reply}

    # ── Agent (tool-calling) ──────────────────────────────────────────────
    if not owner_graph:
        return {"reply": "⚠️ Your account connection isn't set up yet. Please activate the bot from the platform settings."}

    try:
        from src.agent import run_command_bot
        from pathlib import Path as _Path
        digest_emails  = state.get("digest_emails") or []
        owner_data_dir = c.get("owner_data_dir")
        reply = run_command_bot(
            text, owner_graph, wiki_dir, settings,
            history=history,
            digest_context=digest_emails,
            bot_state_path=bot_state_path,
            data_dir=_Path(owner_data_dir) if owner_data_dir else None,
        ).strip()
        if not reply or reply in ("Done.", "Agent loop completed.", "I've processed your request."):
            reply = "I'm not sure how to help with that — could you rephrase?"
    except Exception as e:
        reply = f"Sorry, something went wrong: {e}"

    # ── Draft reminder (keeps draft alive through command turns) ──────────
    pending_draft = state.get("pending_draft")
    if pending_draft:
        queue     = state.get("pending_queue") or []
        q_hint    = f" + {len(queue)} more queued" if queue else ""
        subject   = pending_draft.get("subject", "email")
        reply += (
            f"\n\n_(Draft pending: \"{subject}\"{q_hint} — "
            f"say \"ok\" to save or \"skip\" to discard)_"
        )

    # Update history (command turns are part of conversation)
    new_history = (history + [
        {"role": "user",      "content": text},
        {"role": "assistant", "content": reply},
    ])[-20:]

    return {"reply": reply, "chat_history": new_history}
