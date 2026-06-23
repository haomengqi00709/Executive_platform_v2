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


def _seed_followup(tmp_path, items):
    import json
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "followup_needed.json").write_text(json.dumps(
        {"id": "followup_needed", "status": "fresh", "items": items, "handled": [], "count": len(items)}))


def test_dismiss_followup_acts_on_followup_needed_and_sticks(tmp_path):
    """The original痛点, fixed: 'skip the follow up to daniel' resolves against the LIVE
    followup_needed list, records a durable followup_dismissed annotation, and the item drops
    off the followup_needed read immediately (and stays off)."""
    import json
    from src.bot_tools.email.dismiss_email_followup.tool import build
    from src.bot_tools.sections.read_module_result.tool import build as build_read
    _seed_followup(tmp_path, [
        {"email_id": "S1", "to_email": "daniel@trustai.com", "to_name": "Daniel",
         "subject": "Testing", "sent": "2026-06-20T00:00:00Z", "days_waiting": 3, "urgency": "medium"},
        {"email_id": "S2", "to_email": "other@x.com", "to_name": "Other",
         "subject": "Proposal", "sent": "2026-06-21T00:00:00Z", "days_waiting": 2, "urgency": "high"}])
    out = build(_ctx(tmp_path))("daniel")
    assert "Dismissed 1" in out, out
    data = json.loads(build_read(_ctx(tmp_path, settings={"timezone": "UTC"}))("followup_needed"))
    subs = {it["subject"] for it in data["items"]}
    assert "Testing" not in subs and "Proposal" in subs, subs


def test_dismiss_followup_no_match_honest(tmp_path):
    from src.bot_tools.email.dismiss_email_followup.tool import build
    _seed_followup(tmp_path, [{"email_id": "S1", "to_email": "a@x.com", "to_name": "A", "subject": "X"}])
    out = build(_ctx(tmp_path))("nobody")
    assert "can't find a follow-up" in out


def test_followup_dismiss_does_not_leak_into_reply_needed(tmp_path):
    """Kind isolation: dismissing a follow-up to X must NOT hide an INBOUND reply_needed from X
    (same person + subject, opposite direction)."""
    es.mark_handled(tmp_path, counterparty="daniel@trustai.com", subject="Testing",
                    kind="followup_dismissed", source="dismiss_followup")
    kept, moved = es.overlay_handled(
        tmp_path, [{"email_id": "E1", "from_email": "daniel@trustai.com", "subject": "Testing"}],
        kinds=es.REPLY_KINDS, key_field="from_email")
    assert len(kept) == 1 and len(moved) == 0


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
