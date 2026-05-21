"""
Draft-selection handler — fired right after the digest prompt.

The user is shown a numbered email list and asked "Reply 1/2/all/skip".
This node parses that response, fetches each selected email's body from
Graph, generates 3 reply options, and loads them into the draft queue
so the existing draft approval flow takes over.
"""
from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState


def draft_select_node(state: BotState, config: RunnableConfig) -> dict:
    intent       = state.get("intent")
    emails       = state.get("draft_select_emails") or []
    c            = config.get("configurable", {})
    ai           = c.get("ai")
    owner_graph  = c.get("owner_graph")
    settings     = c.get("owner_settings") or {}
    owner_name   = settings.get("display_name") or "the CEO"
    writing_style = settings.get("writing_style_note") or ""

    _clear = {"pending_state": "idle", "draft_select_emails": None}

    if intent == "draft_select_skip" or not emails or not owner_graph:
        return {**_clear, "reply": "⏭️ Skipping drafts — just ask when you need one."}

    # Determine which emails were selected
    if intent == "draft_select_all":
        selected = emails
    else:  # draft_select_nums
        raw  = re.findall(r'\d+', state.get("text", ""))
        idxs = [int(n) - 1 for n in raw]
        selected = [emails[i] for i in idxs if 0 <= i < len(emails)]

    if not selected:
        return {**_clear, "reply": "No valid numbers — skipping. Ask me when you're ready."}

    # Build draft queue: fetch body + generate 3 reply options per email
    from src.modules.email_monitor import _generate_suggested_replies  # noqa: PLC0415

    queue = []
    for item in selected:
        msg_id = item.get("msg_id", "")
        try:
            msg = owner_graph.get(
                f"/me/messages/{msg_id}",
                params={"$select": "id,subject,from,body,bodyPreview"},
            )
        except Exception:
            msg = {}

        sender_email = item.get("from") or ""
        fake_email   = {
            **msg,
            "subject": item["subject"],
            "from":    {"emailAddress": {"address": sender_email, "name": item["from_name"]}},
        }
        replies = _generate_suggested_replies(
            fake_email, "",
            ai, owner_name=owner_name, writing_style_note=writing_style,
        )
        queue.append({
            "to_name":           item["from_name"],
            "to_email":          sender_email,
            "subject":           f"Re: {item['subject']}",
            "draft_text":        replies[0] if replies else f"Best regards,\n{owner_name}",
            "suggested_replies": replies,
            "original_snippet":  (msg.get("bodyPreview") or item.get("subject", ""))[:200],
        })

    first     = queue.pop(0)
    remaining = f" ({len(queue)} more after)" if queue else ""
    reply = (
        f"📝 Draft for **{first['to_name']}** — {first['subject']}{remaining}:\n\n"
        f"{first['draft_text']}\n\n"
        f"\"ok\" to save · \"1\"/\"2\"/\"3\" for other options · \"skip\" to pass · or type edits"
    )
    return {
        "pending_state":       "draft",
        "pending_draft":       first,
        "pending_queue":       queue,
        "draft_select_emails": None,
        "reply":               reply,
    }
