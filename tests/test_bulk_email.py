"""CRM bulk email — two-phase engine: generate_bulk() then commit_bulk().

Guards the safety-critical behaviour:
  - generate_bulk touches NO Outlook (no draft, no send) — it only previews
  - template mode substitutes placeholders without calling AI
  - personalize mode calls AI once per contact
  - commit_bulk with send=False NEVER calls send_mail (the 'drafts only' red line)
  - commit_bulk with send=True routes through send_mail, creates no drafts
  - oversized send batches are rejected by BULK_SEND_CAP (zero side effects)
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PROD_CLIENT_ID", "test-cid")
os.environ.setdefault("PROD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import outreach  # noqa: E402
from src.modules.outreach import generate_bulk, commit_bulk  # noqa: E402


class FakeGraph:
    def __init__(self):
        self.drafts = []
        self.sent = []

    def create_draft(self, subject, body, to, mailbox=None):
        self.drafts.append({"subject": subject, "body": body, "to": to})
        return {"webLink": f"https://outlook/{to}"}

    def send_mail(self, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})


class FakeAI:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return '{"subject": "AI subject", "body": "<p>AI body</p>"}'


def _seed_crm(data_dir, extra=None):
    contacts = {
        "alice@acme.com": {"email": "alice@acme.com", "name": "Alice Wong",
                           "company": "Acme", "writing_style": "casual",
                           "summary": "Met at TechConf."},
        "bob@globex.com": {"email": "bob@globex.com", "name": "Bob Lee",
                           "company": "Globex"},
    }
    if extra:
        contacts.update(extra)
    (Path(data_dir) / "crm.json").write_text(json.dumps({"contacts": contacts}))


# ── Phase 1: generate (preview only, never touches Outlook) ──────────────────

def test_generate_template_no_ai(tmp_path):
    _seed_crm(tmp_path)
    ai = FakeAI()
    res = generate_bulk(
        ai=ai, data_dir=tmp_path, settings={},
        emails=["alice@acme.com", "bob@globex.com"],
        subject="Hi {first_name}", body="Hello {name} at {company}.",
        personalize=False,
    )
    assert res["status"] == "fresh"
    assert ai.calls == 0                       # template path: no AI
    assert len(res["items"]) == 2
    assert sorted(it["subject"] for it in res["items"]) == ["Hi Alice", "Hi Bob"]
    alice = next(it for it in res["items"] if it["to"] == "alice@acme.com")
    assert alice["body"] == "Hello Alice Wong at Acme."
    # preview.json was written for the UI to poll
    preview = json.loads((tmp_path / "outreach" / "preview.json").read_text())
    assert preview["status"] == "fresh" and len(preview["items"]) == 2


def test_generate_personalize_calls_ai_per_contact(tmp_path):
    _seed_crm(tmp_path)
    ai = FakeAI()
    res = generate_bulk(
        ai=ai, data_dir=tmp_path, settings={},
        emails=["alice@acme.com", "bob@globex.com"],
        subject="", body="invite to the June webinar", personalize=True,
    )
    assert ai.calls == 2
    assert len(res["items"]) == 2
    assert all(it["subject"] == "AI subject" for it in res["items"])


def test_generate_skips_unknown_emails(tmp_path):
    _seed_crm(tmp_path)
    res = generate_bulk(
        ai=FakeAI(), data_dir=tmp_path, settings={},
        emails=["alice@acme.com", "ghost@nowhere.com"],
        subject="Hi", body="hello {name}", personalize=False,
    )
    assert len(res["items"]) == 1 and res["items"][0]["to"] == "alice@acme.com"


# ── Phase 2: commit (only here does anything reach Outlook) ──────────────────

def test_commit_drafts_only(tmp_path):
    g = FakeGraph()
    items = [{"to": "alice@acme.com", "name": "Alice", "company": "Acme",
              "subject": "Hello", "body": "Body text"}]
    res = commit_bulk(graph=g, data_dir=tmp_path, settings={}, items=items, send=False)
    assert len(g.drafts) == 1
    assert g.sent == []                        # red line: drafts only
    assert res["summary"]["drafts"] == 1 and res["summary"]["sent"] == 0


def test_commit_send_uses_send_mail_not_drafts(tmp_path):
    g = FakeGraph()
    items = [{"to": "alice@acme.com", "subject": "Hi", "body": "Body"}]
    res = commit_bulk(graph=g, data_dir=tmp_path, settings={}, items=items, send=True)
    assert len(g.sent) == 1
    assert g.drafts == []
    assert res["summary"]["sent"] == 1 and res["summary"]["drafts"] == 0


def test_commit_send_cap_rejects_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(outreach, "BULK_SEND_CAP", 1)
    g = FakeGraph()
    items = [{"to": "a@x.com", "subject": "s", "body": "b"},
             {"to": "b@x.com", "subject": "s", "body": "b"}]
    res = commit_bulk(graph=g, data_dir=tmp_path, settings={}, items=items, send=True)
    assert res["status"] == "not_run"
    assert g.sent == [] and g.drafts == []     # nothing went out
    assert "too large" in res.get("error", "").lower()


def test_commit_skips_incomplete_items(tmp_path):
    g = FakeGraph()
    items = [
        {"to": "alice@acme.com", "subject": "Hi", "body": "Body"},  # ok
        {"to": "not-an-email", "subject": "Hi", "body": "Body"},    # bad addr
        {"to": "carol@x.com", "subject": "", "body": "Body"},       # empty subject
    ]
    res = commit_bulk(graph=g, data_dir=tmp_path, settings={}, items=items, send=False)
    assert len(g.drafts) == 1
    assert res["summary"]["errors"] == 2
