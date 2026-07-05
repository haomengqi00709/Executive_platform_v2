"""The bot had NO way to search the user's own data — "do I have an email about X" fell
back to two 14-day section caches (false negatives) or an unrelated section run. These
guard the unified search tool: one entry, five deterministic domain backends, results
registered into the existing #N-addressable list types so open/reply follow-ups work."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_search_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_search():
    spec = importlib.util.spec_from_file_location(
        "search_tool",
        str(Path(__file__).resolve().parents[1] / "src" / "bot_tools" / "search" / "search" / "tool.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGraph:
    def __init__(self):
        self.calls = []

    def search_messages(self, query, top=25):
        self.calls.append(("search_messages", query, top))
        return [{"id": "m1", "subject": "Diar-Engineering-Use-Case draft",
                 "from": {"emailAddress": {"address": "bassem@diargroup.com"}},
                 "receivedDateTime": "2026-05-01T10:00:00Z", "bodyPreview": "use case doc",
                 "hasAttachments": True}]

    def get_calendar_view(self, start_dt, end_dt, top=250):
        self.calls.append(("get_calendar_view", start_dt, end_dt))
        return [
            {"id": "e1", "subject": "Vistergy intro call",
             "start": {"dateTime": "2026-06-10T15:00:00"}, "attendees":
             [{"emailAddress": {"address": "davida@vistergy.com"}}], "location": {}},
            {"id": "e2", "subject": "Dentist",
             "start": {"dateTime": "2026-06-11T09:00:00"}, "attendees": [], "location": {}},
        ]

    def search_drive(self, query, top=20):
        self.calls.append(("search_drive", query))
        return [{"id": "f1", "name": "NDA_signed.pdf", "size": 2048,
                 "lastModifiedDateTime": "2026-06-01T00:00:00Z", "webUrl": "http://x"}]


class Ctx:
    def __init__(self, graph, data_dir):
        self.owner_graph = graph
        self.state = {}
        self.data_dir = data_dir


def _mk(tmp_path, crm_contacts=None):
    if crm_contacts is not None:
        (tmp_path / "crm.json").write_text(json.dumps({"contacts": crm_contacts}))
    g = FakeGraph()
    ctx = Ctx(g, tmp_path)
    return _load_search().build(ctx), g, ctx


def test_emails_domain_searches_full_mailbox_and_registers_email_list(tmp_path):
    fn, g, ctx = _mk(tmp_path)
    out = json.loads(fn(what="emails", query="Diar-Engineering-Use-Case"))
    assert g.calls[0][:2] == ("search_messages", "Diar-Engineering-Use-Case")
    assert out[0]["email_id"] == "m1" and out[0]["index"] == 1
    reg = ctx.state["_shown_lists"]["emails"]          # same list type as get_recent_emails
    assert reg["items"][0]["id"] == "m1" if "items" in reg else reg  # registered for #N follow-ups


def test_attachments_domain_uses_attachment_kql(tmp_path):
    fn, g, _ = _mk(tmp_path)
    fn(what="attachments", query="NDA.pdf")
    assert g.calls[0][1] == "attachment:NDA.pdf"


def test_contacts_domain_matches_tokens_in_any_order(tmp_path):
    # the exact failure from the real session: "jason hao" vs CRM name "Hao Jason"
    fn, _, _ = _mk(tmp_path, crm_contacts={
        "haomengqi12138@gmail.com": {"email": "haomengqi12138@gmail.com",
                                     "name": "Hao Jason", "company": ""},
        "bob@acme.com": {"email": "bob@acme.com", "name": "Bob Smith", "company": "Acme"},
    })
    out = json.loads(fn(what="contacts", query="jason hao"))
    assert len(out) == 1 and out[0]["email"] == "haomengqi12138@gmail.com"


def test_meetings_domain_matches_title_or_attendee(tmp_path):
    fn, _, _ = _mk(tmp_path)
    by_title = json.loads(fn(what="meetings", query="vistergy"))
    assert [e["event_id"] for e in by_title] == ["e1"]
    by_attendee = json.loads(fn(what="meetings", query="davida"))
    assert [e["event_id"] for e in by_attendee] == ["e1"]


def test_files_domain_uses_drive_search(tmp_path):
    fn, g, _ = _mk(tmp_path)
    out = json.loads(fn(what="files", query="NDA"))
    assert g.calls[0] == ("search_drive", "NDA")
    assert out[0]["name"] == "NDA_signed.pdf"


def test_no_match_is_honest_not_fabricated(tmp_path):
    fn, g, _ = _mk(tmp_path, crm_contacts={})
    g.search_messages = lambda q, top=25: []
    out = fn(what="emails", query="zzz-nonexistent")
    assert "No emails matched" in out and "honestly" in out


def test_unknown_domain_and_empty_query_are_rejected(tmp_path):
    fn, _, _ = _mk(tmp_path)
    assert "Unknown search domain" in fn(what="everything", query="x")
    assert "Need a search query" in fn(what="emails", query="")
