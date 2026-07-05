"""A fallback turn is dropped from history (anti-poisoning) but HONEST_FALLBACK invites
"try again" — the retry arrived with its referent erased and bound to the freshest thing in
history (live incident: re-ran the Market Intelligence briefing). The failed ask now travels
in STATE and a retry phrase is rewritten to the original ask IN CODE (_effective_ask) — a
prompt-note version lost to history pull in live testing (flash re-answered an old topic).
These guard the lifecycle: record → pop once → substitute; TTL; retry-chains keep the root ask."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_failedask_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot import (_effective_ask, _pop_failed_ask, _record_failed_ask,  # noqa: E402
                     _retryish, _FAILED_ASK_TTL)

ASK = "我的email里面有没有这个: Diar-Engineering-Use-Case"


def test_record_then_pop_once_then_gone():
    state = {}
    _record_failed_ask(state, ASK, None)
    popped = _pop_failed_ask(state)
    assert popped and popped["text"] == ASK
    assert "_last_failed_ask" not in state       # one-shot
    assert _pop_failed_ask(state) is None        # second turn: nothing


def test_expired_marker_is_dropped():
    state = {"_last_failed_ask": {"text": ASK, "ts": time.time() - _FAILED_ASK_TTL - 5}}
    assert _pop_failed_ask(state) is None
    assert "_last_failed_ask" not in state


def test_retry_phrase_is_rewritten_to_original_ask():
    eff = _effective_ask("try again", {"text": ASK, "ts": time.time()})
    assert eff.startswith(ASK)                       # model sees the REAL request first
    assert "RETRY the request above" in eff
    assert "do not re-run a section/briefing" in eff.lower()  # the exact live misfire


def test_new_topic_is_not_rewritten():
    eff = _effective_ask("summarize my meetings this week", {"text": ASK, "ts": time.time()})
    assert eff == "summarize my meetings this week"  # substitution only for retry phrases


def test_no_marker_means_no_rewrite():
    assert _effective_ask("try again", None) == "try again"


def test_failing_retry_chain_keeps_original_ask():
    # turn 1 fails → recorded; turn 2 "try again" ALSO fails → marker must keep the ROOT ask
    state = {}
    _record_failed_ask(state, ASK, None)
    prev = _pop_failed_ask(state)
    _record_failed_ask(state, "try again", prev)
    assert state["_last_failed_ask"]["text"] == ASK


def test_retryish_boundaries():
    assert _retryish("try again") and _retryish("再试一次") and _retryish("retry")
    assert not _retryish("search my email again for the Apollo contract and the NDA")
    assert not _retryish("what are my meetings")
