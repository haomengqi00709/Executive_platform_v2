"""
Meeting draft handler — follow-up email queue after M03 processing.

Intents: meeting_send, meeting_skip, meeting_wait
Pops from pending_meeting_drafts queue; clears pending_state when queue empty.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def meeting_node(state: BotState, config: RunnableConfig) -> dict:
    intent = state.get("intent")
    queue  = list(state.get("pending_meeting_drafts") or [])
    c      = _cfg(config)
    owner_graph = c.get("owner_graph")

    if not queue:
        return {"reply": "No pending meeting follow-ups.", "pending_state": "idle"}

    draft = queue[0]

    # ── send ──────────────────────────────────────────────────────────────
    if intent == "meeting_send":
        sent, failed = 0, 0
        if owner_graph:
            body_html = draft.get("body", "").replace("\n", "<br>")
            for addr in draft.get("attendees", []):
                try:
                    owner_graph.send_mail(addr, draft["subject"], body_html)
                    sent += 1
                except Exception:
                    failed += 1

        queue.pop(0)
        parts = [f"✅ Follow-up email sent to {sent} participant(s) — {draft['title']}."]
        if failed:
            parts.append(f"⚠️ {failed} address(es) failed.")

        if queue:
            nxt = queue[0]
            parts.append(
                f"\n📧 Next: follow-up for \"{nxt['title']}\" "
                f"({len(nxt['attendees'])} participant(s)). Reply send or skip."
            )
            new_state = "meeting"
        else:
            new_state = "idle"

        return {
            "reply":                  "\n".join(parts),
            "pending_meeting_drafts": queue,
            "pending_state":          new_state,
        }

    # ── skip ──────────────────────────────────────────────────────────────
    if intent == "meeting_skip":
        queue.pop(0)
        reply_msg = f"⏭️ Skipped follow-up for \"{draft['title']}\"."
        if queue:
            nxt = queue[0]
            reply_msg += (
                f"\n📧 Next: \"{nxt['title']}\" "
                f"({len(nxt['attendees'])} participant(s)). Reply send or skip."
            )
            new_state = "meeting"
        else:
            new_state = "idle"

        return {
            "reply":                  reply_msg,
            "pending_meeting_drafts": queue,
            "pending_state":          new_state,
        }

    # ── wait (ambiguous reply) ────────────────────────────────────────────
    return {
        "reply": (
            f"📧 Pending follow-up: \"{draft['title']}\" "
            f"({len(draft.get('attendees', []))} participant(s)).\n"
            "Reply send to email it now, or skip to dismiss."
        )
    }
