"""Anti history-poisoning borrows from Hermes. A turn that lists a stored record WITHOUT calling any
tool (answered from memory / replayed history) must not be persisted — replayed flat it teaches the
model to parrot the stale answer instead of calling the lookup tool. Plus: the system prompt carries
a 'fetch fresh / never answer from memory' contract."""
from src.bot import _is_poisoned_turn, _FRESH_FETCH_CONTRACT


# ── poisoned (drop): record listing with NO tool call ────────────────────────
def test_toolless_contact_list_with_email_is_poisoned():
    out = ('I found these contacts for "Jason Hao":\n'
           '* [#1] Jason Hao — jason.hao@ipsconsultancy.ca\n'
           '* [#2] Jason Hao — outlook_3daef@outlook.com')
    assert _is_poisoned_turn(out, []) is True


def test_email_address_without_tool_is_poisoned():
    assert _is_poisoned_turn("Sarah's email is sarah@acme.com", []) is True


def test_contact_leadin_without_tool_is_poisoned():
    assert _is_poisoned_turn("Here are the contacts you asked about:", []) is True


def test_two_list_lines_without_tool_is_poisoned():
    assert _is_poisoned_turn("1. Acme Corp\n2. Globex Inc", []) is True


# ── NOT poisoned (keep) — any tool ran, or no record-listing signal ──────────
def test_any_tool_call_is_never_poisoned():
    out = 'I found these contacts: jason@x.com'
    assert _is_poisoned_turn(out, ["find_contacts_by_name"]) is False


def test_read_module_result_list_is_not_poisoned():
    # the false-positive guard: a followup list from read_module_result lists [#N] + emails, but a tool
    # ran (read_module_result is NOT in the narrow lookup set — so we key off "any tool ran", not that set)
    out = "[#1] daniel@x.com — Re: Apollo\n[#2] alex@y.com — Beta"
    assert _is_poisoned_turn(out, ["read_module_result"]) is False


def test_greeting_is_not_poisoned():
    assert _is_poisoned_turn("Hi! How can I help you today?", []) is False


def test_decline_is_not_poisoned():
    assert _is_poisoned_turn("I can't move calendar events, but I can draft a reschedule note.", []) is False


def test_single_numbered_line_is_not_poisoned():
    assert _is_poisoned_turn("Step 1. I'll draft it now.", []) is False


def test_empty_text_is_not_poisoned():
    assert _is_poisoned_turn("", []) is False


# ── the system-prompt contract is present with its anchors ───────────────────
def test_contract_has_anchors():
    c = _FRESH_FETCH_CONTRACT.lower()
    assert "never answer from memory" in c
    assert "reference only" in c
    assert "re-fetch" in c
    assert "#n" in c        # the carve-out that preserves CURRENT VIEWS / cross-turn #N resolution
