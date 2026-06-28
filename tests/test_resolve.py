"""Unit tests for the shared #N/id/keyword resolver (src/bot_tools/_resolve.resolve_in_list).
These pin the matching behaviour every list domain (commitments/projects/email) shares."""
from types import SimpleNamespace

from src.bot_tools._resolve import resolve_in_list

ITEMS = [
    {"id": "i1", "email_id": "E1", "name": "Alice Smith", "subject": "Alpha deal"},
    {"id": "i2", "email_id": "E2", "name": "Bob Jones", "subject": "Beta proposal"},
    {"id": "i3", "email_id": "E3", "name": "Carol Lee", "subject": "Gamma — MEP Ai Tools"},
]
KW = ("name", "subject")


def _ctx(state=None):
    return SimpleNamespace(state=state or {})


def test_positional_basic():
    assert resolve_in_list("2", ITEMS, keyword_fields=KW)["id"] == "i2"


def test_positional_out_of_range_is_none():
    assert resolve_in_list("9", ITEMS, keyword_fields=KW) is None
    assert resolve_in_list("0", ITEMS, keyword_fields=KW) is None


def test_exact_id_and_alias():
    assert resolve_in_list("i3", ITEMS, keyword_fields=KW)["id"] == "i3"
    # alias field only matches when declared
    assert resolve_in_list("E2", ITEMS, keyword_fields=KW) is None
    assert resolve_in_list("E2", ITEMS, id_aliases=("email_id",), keyword_fields=KW)["id"] == "i2"


def test_substring_keyword():
    assert resolve_in_list("beta", ITEMS, keyword_fields=KW)["id"] == "i2"
    assert resolve_in_list("alice", ITEMS, keyword_fields=KW)["id"] == "i1"


def test_token_subset_compressed():
    # "Carol MEP" is not a contiguous substring of any one field but both words appear
    assert resolve_in_list("Carol MEP", ITEMS, keyword_fields=KW)["id"] == "i3"


def test_token_subset_ambiguous_returns_none():
    items = [{"id": "a", "name": "Strategy work Acme AI"},
             {"id": "b", "name": "Strategy work Beta AI"}]
    assert resolve_in_list("AI Strategy", items, keyword_fields=("name",)) is None


def test_token_subset_can_be_disabled():
    assert resolve_in_list("Carol MEP", ITEMS, keyword_fields=KW, token_subset=False) is None


def test_snapshot_overrides_position():
    # the user saw a DIFFERENT order; "#1" must map to what they saw (i3), not canonical position 1
    state = {"_shown_lists": {"things": {"source": "sec",
             "items": [{"pos": 1, "id": "i3"}, {"pos": 2, "id": "i1"}]}}}
    got = resolve_in_list("1", ITEMS, ctx=_ctx(state), bucket="things", keyword_fields=KW)
    assert got["id"] == "i3"


def test_snapshot_source_guard_ignores_foreign_bucket():
    state = {"_shown_lists": {"emails": {"source": "reply_needed",
             "items": [{"pos": 1, "id": "i3"}]}}}
    # require_source mismatch → snapshot ignored → canonical position 1 = i1
    got = resolve_in_list("1", ITEMS, ctx=_ctx(state), bucket="emails",
                          require_source="followup_needed", keyword_fields=KW)
    assert got["id"] == "i1"


def test_snapshot_stale_id_falls_back_to_position():
    # snapshot points at an id no longer in the list → fall back to positional, not None
    state = {"_shown_lists": {"things": {"source": "sec",
             "items": [{"pos": 1, "id": "GONE"}]}}}
    got = resolve_in_list("1", ITEMS, ctx=_ctx(state), bucket="things", keyword_fields=KW)
    assert got["id"] == "i1"


def test_empty_hint_is_none():
    assert resolve_in_list("", ITEMS, keyword_fields=KW) is None
    assert resolve_in_list("   ", ITEMS, keyword_fields=KW) is None
