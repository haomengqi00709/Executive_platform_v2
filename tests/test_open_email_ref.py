"""'open 1' failed live: the model transcribed the 152-char Graph id from context and corrupted
it (repeated substrings → Graph 400). open_email now resolves a bare/#N position through
_shown_lists['emails'] in CODE — the model passes '1', never re-types a long id. These guard the
resolver: position→exact id; stale-list protection; honest errors instead of a Graph call."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_open_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FULL_ID = "AAMkAGU5NGQyMjk4LWZmYmUtNDY4ZS1hNjljLTU5Yjc3ODczMGZhYgBGAAAAAABNcASK" * 2


def _load():
    spec = importlib.util.spec_from_file_location(
        "open_email_tool",
        str(Path(__file__).resolve().parents[1] / "src" / "bot_tools" / "email" / "open_email" / "tool.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGraph:
    def __init__(self):
        self.opened = []

    def get_message(self, mid):
        self.opened.append(mid)
        if mid != FULL_ID:
            raise RuntimeError("400 Bad Request")
        return {"id": mid, "subject": "Apollo contract", "body": {"content": "sign it"},
                "from": {"emailAddress": {"address": "a@b.com"}}, "toRecipients": []}


class Ctx:
    def __init__(self, graph, state, data_dir):
        self.owner_graph = graph
        self.state = state
        self.data_dir = data_dir


def _emails_bucket(ts=100.0):
    return {"ts": ts, "id_field": "email_id",
            "items": [{"pos": 1, "id": FULL_ID, "label": "Apollo"},
                      {"pos": 2, "id": FULL_ID[:-4] + "XXXX", "label": "Other"}]}


def test_bare_position_resolves_to_exact_id(tmp_path):
    g = FakeGraph()
    fn = _load().build(Ctx(g, {"_shown_lists": {"emails": _emails_bucket()}}, tmp_path))
    out = json.loads(fn("1"))
    assert g.opened == [FULL_ID]          # exact id, zero transcription
    assert out["subject"] == "Apollo contract"


def test_hash_n_form_also_resolves(tmp_path):
    g = FakeGraph()
    fn = _load().build(Ctx(g, {"_shown_lists": {"emails": _emails_bucket()}}, tmp_path))
    json.loads(fn("#1"))
    assert g.opened == [FULL_ID]


def test_position_beyond_list_is_honest_no_graph_call(tmp_path):
    g = FakeGraph()
    fn = _load().build(Ctx(g, {"_shown_lists": {"emails": _emails_bucket()}}, tmp_path))
    out = fn("7")
    assert "No email at position 7" in out and g.opened == []


def test_digit_without_any_shown_list_asks_for_search_first(tmp_path):
    g = FakeGraph()
    fn = _load().build(Ctx(g, {}, tmp_path))
    out = fn("1")
    assert "No email list is currently shown" in out and g.opened == []


def test_fresher_non_email_list_does_not_positional_resolve(tmp_path):
    # "open 1" right after a commitments list (fresher) must NOT open stale email #1
    g = FakeGraph()
    state = {"_shown_lists": {"emails": _emails_bucket(ts=100.0),
                              "commitments": {"ts": 200.0, "items": [{"pos": 1, "id": "c1"}]}}}
    fn = _load().build(Ctx(g, state, tmp_path))
    fn("1")
    assert g.opened != [FULL_ID]           # did not silently open the stale email


def test_full_id_still_works_directly(tmp_path):
    g = FakeGraph()
    fn = _load().build(Ctx(g, {}, tmp_path))
    out = json.loads(fn(FULL_ID))
    assert out["email_id"] == FULL_ID
