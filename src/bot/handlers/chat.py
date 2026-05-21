"""
Chat handler — general AI conversation with history.

Uses Gemini with business_context from owner_settings.
If a draft is pending, appends a reminder at the end.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def chat_node(state: BotState, config: RunnableConfig) -> dict:
    c           = _cfg(config)
    ai          = c.get("ai")
    settings    = c.get("owner_settings") or {}
    name        = settings.get("display_name") or "the CEO"
    biz_ctx     = settings.get("business_context") or ""
    history     = state.get("chat_history") or []
    text        = state.get("text", "")
    sender      = state.get("sender", "Colleague")

    system = (
        f"You are an AI executive assistant working on behalf of {name}. "
        "A trusted colleague is chatting with you via Microsoft Teams. "
        "Answer concisely and professionally. "
        "Do NOT make up specific emails, meetings, or calendar events — "
        "only answer from what you genuinely know."
    )
    if biz_ctx:
        system += f"\n\nBusiness context: {biz_ctx}"

    conv = "\n".join(
        f"{'You' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
        for h in history[-10:]
    )
    prompt = f"{system}\n\n{conv}\n\n{sender}: {text}\n\nAssistant:"

    try:
        reply = ai.generate(prompt).strip()
    except Exception as e:
        reply = f"Sorry, I encountered an error: {e}"

    # Remind user if a draft is pending
    pending_draft = state.get("pending_draft")
    if pending_draft:
        subject = pending_draft.get("subject", "email")
        reply += f"\n\n_(Draft pending: \"{subject}\" — say \"ok\" to save, \"skip\" to discard)_"

    new_history = (history + [
        {"role": "user",      "content": text},
        {"role": "assistant", "content": reply},
    ])[-20:]

    return {"reply": reply, "chat_history": new_history}
