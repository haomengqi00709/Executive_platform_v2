"""A fallback turn is dropped from history (anti-poisoning) but HONEST_FALLBACK invites
"try again" — the retry arrived with its referent erased and bound to the freshest thing in
history (live incident: re-ran the Market Intelligence briefing). The failed ask now travels
in STATE: recorded on fallback, injected next turn as a one-shot note. These guard that
lifecycle: record → inject once → gone; TTL expiry; retry-chains keep the ORIGINAL ask."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_failedask_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot import _failed_ask_note, _record_failed_ask, _retryish, _FAILED_ASK_TTL  # noqa: E402

ASK = "我的email里面有没有这个: Diar-Engineering-Use-Case"


def test_record_then_inject_once_then_gone():
    state = {}
    _record_failed_ask(state, ASK, None)
    note, popped = _failed_ask_note(state)
    assert ASK in note and "NOT in the chat history" in note
    assert popped and popped["text"] == ASK
    assert "_last_failed_ask" not in state          # one-shot: popped on read
    note2, _ = _failed_ask_note(state)
    assert note2 == ""                               # second turn: nothing injected


def test_expired_marker_is_not_injected():
    state = {"_last_failed_ask": {"text": ASK, "ts": time.time() - _FAILED_ASK_TTL - 5}}
    note, popped = _failed_ask_note(state)
    assert note == "" and popped is None
    assert "_last_failed_ask" not in state           # stale marker cleaned up either way


def test_failing_retry_chain_keeps_original_ask():
    # turn 1 fails → recorded; turn 2 is "try again" and ALSO fails → must keep the ORIGINAL ask
    state = {}
    _record_failed_ask(state, ASK, None)
    _, prev = _failed_ask_note(state)                # turn 2 pops the marker
    _record_failed_ask(state, "try again", prev)     # turn 2 falls back too
    note, _ = _failed_ask_note(state)
    assert ASK in note and "try again" not in note.split("«")[1].split("»")[0]


def test_new_topic_failure_overwrites_with_new_ask():
    state = {}
    _record_failed_ask(state, ASK, None)
    _, prev = _failed_ask_note(state)
    _record_failed_ask(state, "summarize my meetings this week", prev)  # NOT a retry phrase
    note, _ = _failed_ask_note(state)
    assert "summarize my meetings" in note and ASK not in note


def test_retryish_boundaries():
    assert _retryish("try again") and _retryish("再试一次") and _retryish("retry")
    assert not _retryish("search my email again for the Apollo contract and the NDA")  # long = real ask
    assert not _retryish("what are my meetings")


def test_note_forbids_section_rerun_misfire():
    # the exact live misfire: "try again" → re-ran Market Intelligence
    state = {}
    _record_failed_ask(state, ASK, None)
    note, _ = _failed_ask_note(state)
    assert "do NOT re-run a section/briefing" in note
