"""Phase 2 integration: the bot tools write email state/handled through the store, and the
key that approve_draft WRITES is the key reply_needed READS (the critical alignment)."""
from types import SimpleNamespace

from src.modules import email_store as es
from src.modules.subject_match import normalize_subject


def _ctx(tmp_path, **kw):
    base = dict(data_dir=tmp_path, state={}, owner_graph=None, settings={},
                graph=None, wiki_dir=tmp_path, user_model={}, user_model_path=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_approve_draft_records_handled_with_reply_needed_key(tmp_path):
    """approve_draft saves the draft AND records a durable handled annotation whose key matches
    what reply_needed looks up for the ORIGINAL inbound email."""
    from src.bot_tools.email.approve_draft.tool import build

    class FakeGraph:
        def create_draft(self, to, subject, body):
            return {"webLink": "https://outlook/draft/1"}

    ctx = _ctx(tmp_path, owner_graph=FakeGraph(),
               state={"pending_draft": {"to": "Daniel@imodel3d.com",
                                        "subject": "Re: MEP Ai Tools", "body": "Thanks"}},
               settings={"display_name": "Jason"})
    out = build(ctx)()
    assert "saved" in out.lower()

    # reply_needed's Channel-6 read key: original email from daniel, subject "MEP Ai Tools"
    store_handled = es.get_handled_map(tmp_path)
    assert ("daniel@imodel3d.com", normalize_subject("MEP Ai Tools")) in store_handled
    assert es.is_handled(tmp_path, "daniel@imodel3d.com", "MEP Ai Tools")["kind"] == "drafted"


def test_dismiss_followup_through_store(tmp_path):
    """dismiss_email_followup edits pending_priority_followup via the store (atomic), not a raw file."""
    from src.bot_tools.email.dismiss_email_followup.tool import build
    es.save_poller_state(tmp_path, {"pending_priority_followup": [
        {"from_name": "Bob", "from": "bob@x.com", "subject": "Q3 deal"},
        {"from_name": "Alice", "from": "alice@x.com", "subject": "Lunch"}]})
    out = build(_ctx(tmp_path))("bob")
    assert "Removed 1" in out
    rem = es.get_poller_state(tmp_path)["pending_priority_followup"]
    assert len(rem) == 1 and rem[0]["from_name"] == "Alice"


def test_dismiss_followup_no_match(tmp_path):
    from src.bot_tools.email.dismiss_email_followup.tool import build
    es.save_poller_state(tmp_path, {"pending_priority_followup": [
        {"from_name": "Bob", "from": "bob@x.com", "subject": "Q3"}]})
    out = build(_ctx(tmp_path))("nobody")
    assert "No follow-up reminder matched" in out
    assert len(es.get_poller_state(tmp_path)["pending_priority_followup"]) == 1


def test_read_module_result_overlays_handled(tmp_path):
    """The bot's reply_needed read excludes a drafted email IMMEDIATELY (read-time overlay),
    without re-running the section — the end-to-end fix for 'drafted but still shows'."""
    import json
    from src.bot_tools.sections.read_module_result.tool import build
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "reply_needed.json").write_text(json.dumps({
        "id": "reply_needed", "status": "fresh", "items": [
            {"email_id": "E1", "subject": "Re: MEP Ai Tools",
             "from_email": "daniel.zhang@imodel3d.com", "from_name": "daniel",
             "received": "2026-06-18T00:00:00Z", "priority": "medium"},
            {"email_id": "E2", "subject": "Follow-up: Meeting",
             "from_email": "daniel.bin.zhang@ips.ca", "from_name": "Daniel Bin",
             "received": "2026-06-22T00:00:00Z", "priority": "high"}],
        "handled": [], "count": 2}))
    # before drafting: both show
    ctx = _ctx(tmp_path, settings={"timezone": "UTC"})
    before = json.loads(build(ctx)("reply_needed"))
    assert {it["subject"] for it in before["items"]} == {"Re: MEP Ai Tools", "Follow-up: Meeting"}
    # after approve_draft records the annotation: the drafted one drops off the read immediately
    es.mark_handled(tmp_path, counterparty="daniel.zhang@imodel3d.com",
                    subject="Re: MEP Ai Tools", kind="drafted")
    after = json.loads(build(_ctx(tmp_path, settings={"timezone": "UTC"}))("reply_needed"))
    subjects = {it["subject"] for it in after["items"]}
    assert "Re: MEP Ai Tools" not in subjects, "drafted email must be overlaid out at read time"
    assert "Follow-up: Meeting" in subjects


def test_email_monitor_state_helpers_use_store(tmp_path):
    """email_monitor._load/_save now delegate to the store (round-trips + projection synced)."""
    from src.modules.email_monitor import _load_monitor_state, _save_monitor_state
    assert _load_monitor_state(tmp_path)["processed_conv_ids"] == []   # default
    _save_monitor_state(tmp_path, {"processed_conv_ids": ["c1"], "pending_priority_followup": []})
    assert _load_monitor_state(tmp_path)["processed_conv_ids"] == ["c1"]
    # store-backed: a fresh store read sees it too
    assert es.get_poller_state(tmp_path)["processed_conv_ids"] == ["c1"]
