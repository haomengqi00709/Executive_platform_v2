"""Unit tests for the bot's list-completeness guard (_enforce_list_completeness).

Locks approaches 1+3: when the bot reads a list section, the shown list must be the
deterministic full render (stashed by read_module_result in state['_pending_render']),
never a model-truncated subset — while analytical prose answers are left untouched.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ceo_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot import _enforce_list_completeness  # noqa: E402

LABELS = [
    "pay the money owed to hao jason",
    "draft the ndas and basic data",
    "begin onboarding the five people",
]
BLOCK = (
    "**Commitments** — 3 item(s)\n"
    "1. Pay the money owed to Hao Jason\n"
    "2. Draft the NDAs and basic data\n"
    "3. Begin onboarding the five people"
)


def _state():
    return {"_pending_render": {
        "section_id": "commitments_extract",
        "block": BLOCK, "labels": list(LABELS), "count": len(LABELS),
    }}


def test_truncated_enumeration_is_substituted():
    """Model lists 1 of 3 as bullets → guard fills in the full canonical list."""
    text = "Here are your commitments:\n1. Pay the money owed to Hao Jason"
    out = _enforce_list_completeness(text, _state(), "what's my commitment now")
    low = out.lower()
    assert all(lbl in low for lbl in LABELS), "every item must appear after the guard"
    assert "here are your commitments:" in low, "model's preamble is preserved"


def test_complete_reply_is_untouched():
    text = ("1. Pay the money owed to Hao Jason\n"
            "2. Draft the NDAs and basic data\n"
            "3. Begin onboarding the five people")
    out = _enforce_list_completeness(text, _state(), "show my commitments")
    assert out == text, "a complete list must be left exactly as the model wrote it"


def test_analytical_prose_is_untouched():
    """No bullets + not a display request → leave the model's reasoning alone."""
    text = "The most urgent one is to pay the money owed to Hao Jason, due soon."
    out = _enforce_list_completeness(text, _state(), "which commitment is most urgent?")
    assert out == text, "analytical answers must not get the full list dumped on them"


def test_display_request_undershow_is_substituted():
    """User asked to SEE the list but the model showed none → fill it in (the dangerous miss)."""
    text = "You have nothing pressing right now."
    out = _enforce_list_completeness(text, _state(), "show me my commitments")
    low = out.lower()
    assert all(lbl in low for lbl in LABELS)


def test_no_pending_render_is_noop():
    text = "Just a normal chat reply."
    assert _enforce_list_completeness(text, {}, "hi there") == text


def test_pending_render_is_consumed_once():
    """The stash is popped so a later turn's reply isn't re-decorated."""
    st = _state()
    text = "1. Pay the money owed to Hao Jason"
    _enforce_list_completeness(text, st, "show my commitments")
    assert "_pending_render" not in st
    # second call with the same (now-empty) state is a no-op
    assert _enforce_list_completeness("anything", st, "show my commitments") == "anything"
