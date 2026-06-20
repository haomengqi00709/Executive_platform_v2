"""Discovers per-tool modules and binds them to a BotContext.

Layout: bot_tools/<domain>/<tool_name>/{tool.py, tool.md}
  tool.py  → exposes `build(ctx) -> callable` (clean LLM-facing signature) and
             optional `IS_ACTION = True/False`.
  tool.md  → single source of truth for the tool's LLM description: the body is
             injected as the function __doc__ (→ the Gemini schema description),
             and frontmatter `routing:` becomes its line in the system prompt's
             TOOL ROUTING block. `action: true` marks a write tool (ACTION_TOOLS).

build(ctx) returns (tools, action_names, routing_lines) which reply() merges with
any tools still defined inline. When every tool is migrated the inline list is
empty and reply() is pure orchestration.
"""
import importlib.util
from pathlib import Path

_BASE = Path(__file__).parent


def _parse_md(path: Path):
    """Return (frontmatter_dict, body). Frontmatter is a simple `key: value` block
    fenced by --- at the top of the file."""
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    fm, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
            body = parts[2].strip()
    return fm, body


def _load_module(tool_py: Path):
    name = f"_bottool_{tool_py.parent.parent.name}_{tool_py.parent.name}"
    spec = importlib.util.spec_from_file_location(name, tool_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover():
    """All tool.py paths under bot_tools/<domain>/<tool>/, sorted for stable order."""
    return sorted(_BASE.glob("*/*/tool.py"))


def build(ctx):
    """Bind every discovered tool to ctx. Returns (tools, action_names, routing_lines)."""
    tools, action_names, routing = [], set(), []
    for tool_py in discover():
        mod = _load_module(tool_py)
        fn = mod.build(ctx)
        fm, body = _parse_md(tool_py.parent / "tool.md")
        if body:
            fn.__doc__ = body                       # md = the LLM schema description
        tools.append(fn)
        if str(fm.get("action", "")).lower() == "true" or getattr(mod, "IS_ACTION", False):
            action_names.add(fn.__name__)
        r = (fm.get("routing") or "").strip()
        if r:
            routing.append(f"  {fn.__name__:26} → {r}\n")
    return tools, action_names, routing
