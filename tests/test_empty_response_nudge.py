"""Gemini flash returns an empty candidate (finish_reason=STOP, 0 parts) for certain inputs, and
a byte-identical retry stays empty (repro on Daniel's context: "Try again" → 3/3 empty → the
"I looked into that but didn't finish" fallback). The retry now NUDGES: it appends a synthetic
exchange to `contents` before retrying so the model isn't asked the identical question. These
guard: recovery after empties, the nudge actually changes the payload, bounded fallback with no
regression, and finish_reason logging."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_empty_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import bot  # noqa: E402
from src.bot import HONEST_FALLBACK, _MAX_EMPTY_RETRY, _EMPTY_NUDGE  # noqa: E402


# ── fake genai response shapes (the exact fields the retry loop reads) ──
def _empty():
    cand = SimpleNamespace(content=None, finish_reason="STOP")
    return SimpleNamespace(candidates=[cand], usage_metadata=None, prompt_feedback=None)


def _text(txt):
    part = SimpleNamespace(text=txt, function_call=None)
    cand = SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")
    return SimpleNamespace(candidates=[cand], usage_metadata=None, prompt_feedback=None)


class FakeModels:
    def __init__(self, script):
        self.script = script
        self.calls = 0
        self.last_contents = None

    def generate_content(self, **kw):
        self.last_contents = kw.get("contents")
        r = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return r


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


class FakeGraph:
    def __getattr__(self, name):
        return lambda *a, **k: {} if name.startswith(("create", "add", "send", "update")) else []


def _nudge_texts(contents):
    out = []
    for c in contents or []:
        for p in (getattr(c, "parts", None) or []):
            if getattr(p, "text", None):
                out.append(p.text)
    return out


def _run(script, tmp_path, user_text="hello there"):
    fc = FakeClient(script)
    bot._client = lambda: fc                              # monkeypatch the cached client factory
    g = FakeGraph()
    out, _ = bot.reply({}, user_text, g, g, {"display_name": "Jason"}, tmp_path / "wiki", tmp_path)
    return out, fc.models


def test_recovers_after_one_empty(tmp_path):
    out, models = _run([_empty(), _text("Here is your answer.")], tmp_path)
    assert out == "Here is your answer."                 # recovered, NOT the fallback
    assert models.calls == 2                             # 1 empty + 1 nudged retry that succeeded
    assert _EMPTY_NUDGE in _nudge_texts(models.last_contents)  # payload actually changed


def test_recovers_after_two_empties(tmp_path):
    out, models = _run([_empty(), _empty(), _text("Done thinking.")], tmp_path)
    assert out == "Done thinking."
    assert models.calls == 3
    # two nudge pairs appended before success
    assert _nudge_texts(models.last_contents).count(_EMPTY_NUDGE) == 2


def test_always_empty_falls_back_bounded_no_regression(tmp_path):
    out, models = _run([_empty()], tmp_path)             # fake returns empty forever
    assert out == HONEST_FALLBACK                        # worst case == today, no regression
    assert models.calls == 1 + _MAX_EMPTY_RETRY          # bounded: first call + N nudged retries


def test_finish_reason_is_logged_on_empty(tmp_path, capsys):
    _run([_empty(), _text("ok")], tmp_path)
    logged = capsys.readouterr().out
    assert "finish_reason=STOP" in logged and "nudge+retry" in logged


def test_no_empty_no_nudge(tmp_path):
    # a first-call success must not append any nudge
    out, models = _run([_text("immediate answer")], tmp_path)
    assert out == "immediate answer"
    assert models.calls == 1
    assert _EMPTY_NUDGE not in _nudge_texts(models.last_contents)
