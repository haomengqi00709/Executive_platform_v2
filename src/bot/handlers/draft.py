"""
Draft handler — email draft approval flow.

Intents handled: approve, skip, select, revise, question
After approve/skip/select: clears pending_draft, auto-advances pending_queue.
After revise: updates pending_draft, stays in draft flow.
question: answers the question, keeps pending_draft alive.
"""
from __future__ import annotations

import re
from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState

_NO_OWNER_GRAPH = (
    "❌ Cannot save the draft — your Microsoft account connection needs to be refreshed. "
    "Please log out and log back in at the platform, then try again."
)


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def _save_draft(owner_graph, pending: dict) -> str:
    result = owner_graph.create_draft(
        to=pending["to_email"],
        subject=pending["subject"],
        body=pending["draft_text"].replace("\n", "<br>"),
    )
    if result.get("id"):
        return f"✅ Draft saved to Outlook Drafts.\nTo: {pending['to_name']}  |  {pending['subject']}"
    return "⚠️ Draft saved but couldn't confirm the ID."


def _advance_queue(state: BotState, graph_client, chat_id: str) -> dict:
    """Pop next draft from pending_queue, or clear state."""
    queue = list(state.get("pending_queue") or [])
    if queue:
        next_draft = queue.pop(0)
        remaining  = f" ({len(queue)} more after this)" if queue else ""
        try:
            graph_client.send_chat_message(
                chat_id,
                f"📬 Next pending: \"{next_draft.get('subject','?')}\" "
                f"from {next_draft.get('to_name','?')}{remaining}.\n"
                f"Reply \"skip\" to dismiss, or tell me what to do."
            )
        except Exception:
            pass
        return {
            "pending_draft":  next_draft,
            "pending_queue":  queue,
            "pending_state":  "draft",
        }
    return {
        "pending_draft":  None,
        "pending_queue":  [],
        "pending_state":  "idle",
    }


def draft_node(state: BotState, config: RunnableConfig) -> dict:
    intent      = state.get("intent")
    pending     = state.get("pending_draft") or {}
    c           = _cfg(config)
    owner_graph = c.get("owner_graph")
    chat_id     = c.get("chat_id", "")
    graph_client = c.get("graph_client")
    ai          = c.get("ai")
    owner_name  = (c.get("owner_settings") or {}).get("display_name") or "the CEO"

    # ── approve ────────────────────────────────────────────────────────────
    if intent == "approve":
        if not owner_graph:
            return {"reply": _NO_OWNER_GRAPH, **_advance_queue(state, graph_client, chat_id)}
        try:
            reply = _save_draft(owner_graph, pending)
        except Exception as e:
            reply = f"❌ Failed to save draft: {e}"
        return {"reply": reply, **_advance_queue(state, graph_client, chat_id)}

    # ── skip ───────────────────────────────────────────────────────────────
    if intent == "skip":
        reply = f"⏭️ Skipped draft for {pending.get('to_name', 'unknown')}."
        return {"reply": reply, **_advance_queue(state, graph_client, chat_id)}

    # ── select (1 / 2 / 3) ────────────────────────────────────────────────
    if intent == "select":
        idx     = int(state["text"].strip()[0]) - 1
        replies = pending.get("suggested_replies", [])
        chosen  = {**pending, "draft_text": replies[idx]} if replies and 0 <= idx < len(replies) else pending
        if not owner_graph:
            return {"reply": _NO_OWNER_GRAPH, **_advance_queue(state, graph_client, chat_id)}
        try:
            result = owner_graph.create_draft(
                to=chosen["to_email"],
                subject=chosen["subject"],
                body=chosen["draft_text"].replace("\n", "<br>"),
            )
            reply = (
                f"✅ Reply {idx + 1} saved to Outlook Drafts.\n"
                f"To: {chosen['to_name']}  |  {chosen['subject']}"
                if result.get("id") else
                "⚠️ Saved but couldn't confirm draft ID."
            )
        except Exception as e:
            reply = f"❌ Failed to save draft: {e}"
        return {"reply": reply, **_advance_queue(state, graph_client, chat_id)}

    # ── revise ────────────────────────────────────────────────────────────
    if intent == "revise":
        prompt = (
            f"You are revising a draft email on behalf of {owner_name}.\n\n"
            f"Original draft:\n{pending.get('draft_text', '')}\n\n"
            f"Modification requested: {state['text']}\n\n"
            f"Return the revised draft only. End with 'Best regards,\\n{owner_name}':"
        )
        try:
            new_text = ai.generate(prompt).strip()
        except Exception as e:
            return {"reply": f"❌ Failed to revise draft: {e}"}

        updated = {**pending, "draft_text": new_text}
        reply   = (
            f"✏️ Revised draft:\n\n"
            f"── Draft Reply ──\n{new_text}\n\n"
            f"────────────────\n"
            f'"ok" → save · "1"/"2"/"3" → pick original reply · "skip" → discard · or type more changes'
        )
        return {"reply": reply, "pending_draft": updated, "pending_state": "draft"}

    # ── question (while draft pending) ────────────────────────────────────
    # intent == "question" or "chat" (keep draft alive, answer the question)
    prompt = (
        f"You are an AI assistant for {owner_name}.\n"
        f"There is a pending email draft — To: {pending.get('to_name')} | "
        f"Subject: {pending.get('subject')}\n"
        f"Original email snippet: {pending.get('original_snippet', '')}\n"
        f"Current draft:\n{pending.get('draft_text', '')}\n\n"
        f"{owner_name} asks: {state['text']}\n\n"
        f"Answer concisely. Remind at the end: "
        f"'Draft still pending — \"ok\" to save, \"1\"/\"2\"/\"3\" for original replies, \"skip\" to discard.'"
    )
    try:
        answer = (c.get("ai") or ai).generate(prompt).strip()
    except Exception as e:
        answer = f"Sorry, couldn't answer: {e}"
    # pending_draft NOT in return → checkpointer keeps existing value unchanged
    return {"reply": answer}
