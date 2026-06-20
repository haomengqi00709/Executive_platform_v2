"""Per-request context shared by every bot tool.

Tools used to be closures defined inside reply(); migrating them into their own
files (bot_tools/<domain>/<tool>/tool.py) means they can't capture reply()'s
locals anymore, so each tool's build(ctx) closes over this object instead.

`state` is the SAME dict object reply() holds and returns — tools mutate it
IN PLACE (ctx.state["pending_draft"] = ...), never rebind it, so the migrated
tools and any still-inline tools share one source of truth.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BotContext:
    state: dict          # mutable, shared with reply(); mutate in place
    owner_graph: object  # Graph client for the OWNER mailbox/calendar (actions)
    graph: object        # Graph client for the bot account
    settings: dict
    data_dir: Path
    wiki_dir: Path
    user_model: dict = None       # ignored_senders / behavioral_rules / …; mutate in place
    user_model_path: Path = None
