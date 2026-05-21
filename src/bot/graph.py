"""
LangGraph StateGraph for the Teams bot.

Graph: START → router_node → [conditional] → handler_node → send_node → END

Routing:
  approve/skip/select/revise/question/chat(draft) → draft_node
  expense_yes/expense_no/expense_wait             → expense_node
  meeting_send/meeting_skip/meeting_wait          → meeting_node
  command                                         → command_node
  chat                                            → chat_node
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END

from src.bot.state import BotState
from src.bot.router import router_node
from src.bot.handlers.draft        import draft_node
from src.bot.handlers.draft_select import draft_select_node
from src.bot.handlers.expense      import expense_node
from src.bot.handlers.meeting      import meeting_node
from src.bot.handlers.command      import command_node
from src.bot.handlers.chat         import chat_node


def send_node(state: BotState, config: RunnableConfig) -> dict:
    """Single exit point — deliver reply to Teams chat."""
    reply = (state.get("reply") or "").strip()
    if not reply:
        return {}
    c       = config.get("configurable", {})
    client  = c.get("graph_client")
    chat_id = c.get("chat_id", "")
    if client and chat_id:
        client.send_chat_message(chat_id, reply)
    return {}


_DRAFT_INTENTS        = {"approve", "skip", "select", "revise", "question", "chat"}
_DRAFT_SELECT_INTENTS = {"draft_select_all", "draft_select_nums", "draft_select_skip"}
_EXPENSE_INTENTS      = {"expense_yes", "expense_no", "expense_wait"}
_MEETING_INTENTS      = {"meeting_send", "meeting_skip", "meeting_wait"}


def _route(state: BotState) -> str:
    intent = state.get("intent") or "chat"
    if intent in _DRAFT_SELECT_INTENTS:
        return "draft_select"
    if intent in _DRAFT_INTENTS and state.get("pending_state") == "draft":
        return "draft"
    if intent in _EXPENSE_INTENTS:
        return "expense"
    if intent in _MEETING_INTENTS:
        return "meeting"
    if intent == "command":
        return "command"
    return "chat"


def build_graph(checkpointer) -> object:
    builder = StateGraph(BotState)
    builder.add_node("router",       router_node)
    builder.add_node("draft",        draft_node)
    builder.add_node("draft_select", draft_select_node)
    builder.add_node("expense",      expense_node)
    builder.add_node("meeting",      meeting_node)
    builder.add_node("command",      command_node)
    builder.add_node("chat",         chat_node)
    builder.add_node("send",         send_node)
    builder.set_entry_point("router")
    builder.add_conditional_edges(
        "router", _route,
        {"draft_select": "draft_select", "draft": "draft", "expense": "expense",
         "meeting": "meeting", "command": "command", "chat": "chat"},
    )
    for node in ("draft", "draft_select", "expense", "meeting", "command", "chat"):
        builder.add_edge(node, "send")
    builder.add_edge("send", END)
    return builder.compile(checkpointer=checkpointer)
