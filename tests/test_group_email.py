"""CRM group resolution + intent-led bulk-email generation (chat group email).

Guards:
  - resolve_group is EXACT-first (no over-match: 'Investors' != 'potential_investors')
  - substring fallback surfaces candidate tags for disambiguation
  - _generate_bulk_email substitutes all placeholders, parses JSON, and does NOT
    consume a literal {name} the user typed into their intent
  - generate_bulk/commit_bulk honor write_files=False (the chat path must not
    clobber the UI's preview.json / results.json)
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PROD_CLIENT_ID", "test-cid")
os.environ.setdefault("PROD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import crm, outreach  # noqa: E402


class FakeGraph:
    def __init__(self):
        self.drafts = []
        self.sent = []

    def create_draft(self, subject, body, to, mailbox=None):
        self.drafts.append({"subject": subject, "to": to})
        return {"webLink": f"https://outlook/{to}"}

    def send_mail(self, to, subject, html):
        self.sent.append(to)


def _seed(data_dir):
    contacts = {
        "a@x.com": {"email": "a@x.com", "name": "A", "tags": ["investors"]},
        "b@x.com": {"email": "b@x.com", "name": "B", "tags": ["potential_investors"]},
        "c@x.com": {"email": "c@x.com", "name": "C", "tags": ["Investors", "clients"]},
    }
    (Path(data_dir) / "crm.json").write_text(json.dumps({"contacts": contacts}))


# ── group resolution ─────────────────────────────────────────────────────────

def test_exact_match_no_overmatch(tmp_path):
    _seed(tmp_path)
    got = sorted(c["email"] for c in crm.find_contacts_by_tag_exact(tmp_path, "Investors"))
    assert got == ["a@x.com", "c@x.com"]          # NOT b (potential_investors)


def test_resolve_group_exact(tmp_path):
    _seed(tmp_path)
    res = crm.resolve_group(tmp_path, "investors")
    assert res["mode"] == "exact"
    assert sorted(c["email"] for c in res["contacts"]) == ["a@x.com", "c@x.com"]


def test_resolve_group_substring_disambiguates(tmp_path):
    _seed(tmp_path)
    res = crm.resolve_group(tmp_path, "invest")
    assert res["mode"] == "substring"
    tags = sorted(g["tag"].lower() for g in res["candidate_tags"])
    assert tags == ["investors", "potential_investors"]


def test_resolve_group_none_lists_all(tmp_path):
    _seed(tmp_path)
    res = crm.resolve_group(tmp_path, "nope")
    assert res["mode"] == "none"
    assert {g["tag"].lower() for g in res["all_groups"]} == {"investors", "potential_investors", "clients"}


def test_list_groups_counts(tmp_path):
    _seed(tmp_path)
    counts = {g["tag"].lower(): g["count"] for g in crm.list_groups(tmp_path)}
    assert counts == {"investors": 2, "potential_investors": 1, "clients": 1}


# ── intent-led generation ────────────────────────────────────────────────────

def test_generate_bulk_email_intent_led(tmp_path):
    class AI:
        def generate(self, p):
            assert "{intent}" not in p and "{contact_name}" not in p     # placeholders filled
            assert "Q3 roadmap" in p and "Alice" in p                    # intent + contact present
            assert "{name}" in p                                         # user's literal {name} NOT consumed
            return '{"subject": "Q3", "body": "<p>Hi Alice</p>"}'
    c = {"email": "a@x.com", "name": "Alice", "company": "Acme", "role": "VP",
         "status": "client", "writing_style": "casual", "summary": "long-time client"}
    d = outreach._generate_bulk_email(AI(), c, intent="the Q3 roadmap for {name}",
                                      display_name="Dan", business_context="We do X")
    assert d == {"subject": "Q3", "body": "<p>Hi Alice</p>"}


# ── write_files=False (chat path must not touch UI files) ─────────────────────

def test_generate_bulk_no_file_write(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(outreach, "_generate_bulk_email",
                        lambda *a, **k: {"subject": "S", "body": "<p>B</p>"})
    res = outreach.generate_bulk(ai=None, data_dir=tmp_path, settings={},
                                 emails=["a@x.com"], body="hi", personalize=True,
                                 write_files=False)
    assert len(res["items"]) == 1
    assert not (tmp_path / "outreach" / "preview.json").exists()


def test_commit_bulk_no_file_write(tmp_path):
    g = FakeGraph()
    items = [{"to": "a@x.com", "name": "A", "company": "", "subject": "S", "body": "B"}]
    res = outreach.commit_bulk(graph=g, data_dir=tmp_path, settings={},
                               items=items, send=False, write_files=False)
    assert len(g.drafts) == 1 and g.sent == []
    assert res["summary"]["drafts"] == 1
    assert not (tmp_path / "outreach" / "results.json").exists()
