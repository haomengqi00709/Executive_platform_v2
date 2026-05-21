"""
Router node — classifies incoming message intent and determines which handler runs.

Priority order:
  1. pending_state == "expense"      → expense (regardless of text)
  2. pending_state == "meeting"      → meeting
  3. pending_state == "draft"
       + rule-based tokens           → approve / skip / select
       + starts with digit 1-3       → select
       + AI classify                 → revise / question / chat
  4. pending_state == "draft_select" → draft_select_all / nums / skip
  5. starts with "/"                 → command (slash)
  6. config keyword fast-path        → command
  7. data-query keyword fast-path    → command
  8. AI classify                     → command / chat
"""
from __future__ import annotations

import re
from langchain_core.runnables import RunnableConfig

from src.bot.state import BotState

# ── token tables (single definition for the whole system) ──────────────────

APPROVE_TOKENS  = frozenset({
    "ok", "okay", "send", "approve", "yes", "good", "perfect",
    "great", "go", "confirmed", "confirm", "fine", "sure",
})
APPROVE_PHRASES = ("looks good", "send it", "go ahead", "that's good",
                   "that's fine", "yes please")

SKIP_TOKENS  = frozenset({"skip", "ignore", "cancel", "no", "pass",
                           "discard", "delete", "next"})
SKIP_PHRASES = ("skip this", "ignore this", "don't send", "no thanks")

EXPENSE_YES = frozenset({"yes", "y", "confirm", "yeah", "yep",
                          "record it", "save it"})
EXPENSE_NO  = frozenset({"no", "n", "skip", "discard", "duplicate", "nope"})

MEETING_SEND = frozenset({"send", "yes", "approve", "go", "confirm",
                           "ok", "okay", "sure"})
MEETING_SKIP = frozenset({"skip", "no", "ignore", "cancel", "pass", "dismiss"})

_COMMAND_KEYWORDS = frozenset({
    "meeting", "calendar", "schedule", "next", "today", "tomorrow",
    "email", "contact", "action", "commitment", "follow", "task",
    "who", "when", "what", "show", "list", "find", "get", "check",
    "briefing", "brief", "summary", "summarize", "summarise",
    "yesterday", "morning", "update", "status", "news", "inbox",
    "past", "last", "recent", "ago", "days", "week", "month",
    "had", "attended", "sent", "received",
})

_CONFIG_KEYWORDS = frozenset({
    "focus", "adjust", "change", "update", "set", "configure",
    "聚焦", "调整", "更改", "设置", "配置",
})


def _cfg(config: dict) -> dict:
    return config.get("configurable", {})


def _is_select(text: str) -> bool:
    return bool(re.match(r"^[123]$", text.strip()))


def _rule_intent(text: str) -> str | None:
    t = text.lower().strip().rstrip(".,! ")
    if t in APPROVE_TOKENS or any(p in t for p in APPROVE_PHRASES):
        return "approve"
    if t in SKIP_TOKENS or any(p in t for p in SKIP_PHRASES):
        return "skip"
    if _is_select(text):
        return "select"
    return None


def _ai_intent_draft(text: str, pending: dict, ai) -> str:
    """Ask AI to classify an ambiguous message when a draft is pending."""
    prompt = (
        "You are classifying a user message in a Teams chat.\n"
        f"Pending email draft — To: {pending.get('to_name')} | "
        f"Subject: {pending.get('subject')}\n"
        f"Draft snippet: {pending.get('draft_text', '')[:150]}\n\n"
        f"User message: \"{text}\"\n\n"
        "Reply with exactly ONE word:\n"
        "  revise   — user wants to change the draft wording\n"
        "  question — user is asking about the draft or related email\n"
        "  chat     — unrelated to the draft (greeting, general question)\n"
    )
    try:
        result = ai.generate(prompt).strip().lower().split()[0]
        if result in ("revise", "question", "chat"):
            return result
    except Exception as e:
        print(f"[Router] AI draft-intent failed: {e}")
    return "revise"


def _ai_intent_general(text: str, ai) -> str:
    """Ask AI: is this a data query (command) or general chat?"""
    prompt = (
        "You are classifying a user message for an executive AI assistant.\n"
        f"Message: \"{text}\"\n\n"
        "Reply with exactly ONE word:\n"
        "  command — user wants data, actions, or to change a setting\n"
        "  chat    — general conversation, greeting, or opinion\n"
    )
    try:
        result = ai.generate(prompt).strip().lower().split()[0]
        if result in ("command", "chat"):
            return result
    except Exception as e:
        print(f"[Router] AI general-intent failed: {e}")
    return "chat"


def router_node(state: BotState, config: RunnableConfig) -> dict:
    """
    Classify intent. Sets state["intent"] which graph edges use for routing.
    Returns only {"intent": ...} — all other state fields unchanged.
    """
    text           = (state.get("text") or "").strip()
    pending_state  = state.get("pending_state") or "idle"
    pending_draft  = state.get("pending_draft")
    c              = _cfg(config)
    ai             = c.get("ai")

    # 1. Expense pending — always routes there regardless of text
    if pending_state == "expense":
        t = text.lower().strip()
        if t in EXPENSE_YES:
            return {"intent": "expense_yes"}
        if t in EXPENSE_NO:
            return {"intent": "expense_no"}
        return {"intent": "expense_wait"}  # ambiguous — stay in expense flow

    # 2. Meeting pending
    if pending_state == "meeting":
        t = text.lower().strip()
        if t in MEETING_SEND or "send it" in t or "send all" in t:
            return {"intent": "meeting_send"}
        if t in MEETING_SKIP or "skip" in t:
            return {"intent": "meeting_skip"}
        return {"intent": "meeting_wait"}

    # 3. Draft pending
    if pending_state == "draft" and pending_draft:
        rule = _rule_intent(text)
        if rule:
            return {"intent": rule}
        # Ambiguous — AI classifies
        intent = _ai_intent_draft(text, pending_draft, ai) if ai else "revise"
        print(f"[Router] draft-pending AI intent: '{text[:40]}' → {intent}")
        return {"intent": intent}

    # 4. Draft selection prompt (after digest)
    if pending_state == "draft_select":
        t = text.lower().strip().rstrip(".,! ")
        if t in ("skip", "none", "no", "cancel"):
            return {"intent": "draft_select_skip"}
        if t == "all":
            return {"intent": "draft_select_all"}
        if re.match(r'^[\d\s,]+$', t):
            return {"intent": "draft_select_nums"}
        return {"intent": "draft_select_skip"}

    # 5. Slash command
    if text.startswith("/"):
        return {"intent": "command"}

    # 6. Config update keywords fast-path → command (agent handles it)
    t_lower = text.lower()
    if any(kw in t_lower for kw in _CONFIG_KEYWORDS):
        return {"intent": "command"}

    # 7. Data-query keywords fast-path
    if any(kw in t_lower for kw in _COMMAND_KEYWORDS):
        return {"intent": "command"}

    # 8. AI classify general message
    intent = _ai_intent_general(text, ai) if ai else "chat"
    print(f"[Router] general AI intent: '{text[:40]}' → {intent}")
    return {"intent": intent}


def route_from_intent(state: BotState) -> str:
    """Conditional edge function used by the graph."""
    return state.get("intent") or "chat"
