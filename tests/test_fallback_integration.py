"""When the primary Gemini call keeps returning empty AND a fallback model is configured, the
bot switches to it for the rest of the turn and drives the SAME tools. These exercise the whole
reply() path with a fake primary (always empty) + a fake fallback: only-on-fallback (never used
when primary works), failure→fallback (text), failure→fallback that drives a TOOL, both-fail and
disabled → HONEST_FALLBACK (no regression)."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_fbint_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402
from src import bot, bot_fallback  # noqa: E402
from src.bot import HONEST_FALLBACK  # noqa: E402


# ── fake PRIMARY (genai) responses ──
def _empty():
    cand = SimpleNamespace(content=None, finish_reason="STOP")
    return SimpleNamespace(candidates=[cand], usage_metadata=None, prompt_feedback=None)


def _text(txt):
    part = SimpleNamespace(text=txt, function_call=None)
    cand = SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")
    return SimpleNamespace(candidates=[cand], usage_metadata=None, prompt_feedback=None)


class FakePrimaryModels:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    def generate_content(self, **kw):
        r = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return r


class FakePrimaryClient:
    def __init__(self, script):
        self.models = FakePrimaryModels(script)


class FakeGraph:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _m(*a, **k):
            self.calls.append(name)
            return {} if name.startswith(("create", "add", "send", "update")) else []
        return _m


def _run(primary_script, fallback_gen, tmp_path, monkeypatch, user_text="hello there", enabled=True):
    pc = FakePrimaryClient(primary_script)
    monkeypatch.setattr(bot, "_client", lambda: pc)
    monkeypatch.setattr(bot_fallback, "is_enabled", lambda: enabled)
    fb_calls = {"n": 0}

    def _wrapped(contents, system, all_tools):
        fb_calls["n"] += 1
        return fallback_gen(fb_calls["n"], contents, all_tools)
    monkeypatch.setattr(bot_fallback, "generate", _wrapped)
    g = FakeGraph()
    out, _ = bot.reply({}, user_text, g, g, {"display_name": "Jason"}, tmp_path / "wiki", tmp_path)
    return out, pc.models, fb_calls, g


def test_fallback_not_used_when_primary_succeeds(tmp_path, monkeypatch):
    out, primary, fb_calls, _ = _run(
        [_text("primary answer")],
        lambda n, c, t: ([types.Part(text="SHOULD NOT BE CALLED")], "stop", None),
        tmp_path, monkeypatch)
    assert out == "primary answer"
    assert fb_calls["n"] == 0                       # fallback never invoked when primary works


def test_primary_empty_then_fallback_text(tmp_path, monkeypatch):
    out, primary, fb_calls, _ = _run(
        [_empty()],                                  # primary empty forever
        lambda n, c, t: ([types.Part(text="fallback saved the turn")], "stop", None),
        tmp_path, monkeypatch)
    assert out == "fallback saved the turn"          # recovered via fallback, not HONEST_FALLBACK
    assert fb_calls["n"] >= 1
    assert primary.calls == 1 + bot._MAX_EMPTY_RETRY  # nudge exhausted BEFORE switching


def test_fallback_drives_a_tool_end_to_end(tmp_path, monkeypatch):
    # fallback returns a tool call first, then a text answer — proving it drives our tools
    def _gen(n, contents, all_tools):
        if n == 1:
            return ([types.Part(function_call=types.FunctionCall(name="get_recent_emails", args={"hours_back": 24}))],
                    "tool_calls", None)
        return ([types.Part(text="Here are your recent emails.")], "stop", None)
    out, primary, fb_calls, graph = _run([_empty()], _gen, tmp_path, monkeypatch)
    assert out == "Here are your recent emails."
    assert fb_calls["n"] == 2                         # tool round + final text, both on fallback
    assert "get_messages" in graph.calls             # the tool actually executed against the graph


def test_both_fail_lands_honest_fallback(tmp_path, monkeypatch):
    out, primary, fb_calls, _ = _run(
        [_empty()],
        lambda n, c, t: ([], "ERROR", None),         # fallback also produces nothing
        tmp_path, monkeypatch)
    assert out == HONEST_FALLBACK                     # no regression when everything fails
    assert fb_calls["n"] >= 1


def test_disabled_fallback_is_never_called(tmp_path, monkeypatch):
    out, primary, fb_calls, _ = _run(
        [_empty()],
        lambda n, c, t: ([types.Part(text="X")], "stop", None),
        tmp_path, monkeypatch, enabled=False)         # fallback OFF (default)
    assert out == HONEST_FALLBACK                     # behaves exactly like before the feature
    assert fb_calls["n"] == 0
