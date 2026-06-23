"""Unit tests for the email SQLite store (Phase 2): poller state + durable handled annotations."""
import json
from datetime import datetime, timedelta, timezone

from src.modules import email_store as es


# ── poller state (Piece A) ───────────────────────────────────────────────────

def test_poller_default_when_empty(tmp_path):
    st = es.get_poller_state(tmp_path)
    assert st["processed_conv_ids"] == [] and st["last_checked_ts"] == ""
    # default must be a fresh copy — mutating it must not leak into the next read
    st["processed_conv_ids"].append("x")
    assert es.get_poller_state(tmp_path)["processed_conv_ids"] == []


def test_poller_roundtrip_and_projection(tmp_path):
    state = {"last_checked_ts": "2026-06-23T00:00:00Z", "processed_conv_ids": ["c1", "c2"],
             "seen_msg_ids": ["m1"], "last_notified_emails": [{"from": "a@b.com", "subject": "Hi"}],
             "pending_priority_followup": []}
    es.save_poller_state(tmp_path, state)
    assert es.get_poller_state(tmp_path) == state
    # projection keeps email_monitor.json in sync for legacy readers
    proj = json.loads((tmp_path / "email_monitor.json").read_text())
    assert proj["processed_conv_ids"] == ["c1", "c2"]


def test_poller_lazy_import_from_json(tmp_path):
    (tmp_path / "email_monitor.json").write_text(json.dumps({
        "last_checked_ts": "2026-06-20T00:00:00Z", "processed_conv_ids": ["old1", "old2"],
        "pending_priority_followup": [{"from_name": "Bob", "subject": "Q3"}]}))
    st = es.get_poller_state(tmp_path)  # first access triggers import
    assert st["processed_conv_ids"] == ["old1", "old2"]
    assert st["pending_priority_followup"][0]["from_name"] == "Bob"


def test_poller_import_idempotent(tmp_path):
    (tmp_path / "email_monitor.json").write_text(json.dumps({"processed_conv_ids": ["a"]}))
    assert es.get_poller_state(tmp_path)["processed_conv_ids"] == ["a"]
    # a later save then a re-open must not re-import the stale file over newer state
    es.save_poller_state(tmp_path, {"processed_conv_ids": ["a", "b"], "pending_priority_followup": []})
    assert es.get_poller_state(tmp_path)["processed_conv_ids"] == ["a", "b"]


# ── durable handled annotations (Piece B) ────────────────────────────────────

def test_mark_and_lookup_handled(tmp_path):
    assert es.mark_handled(tmp_path, counterparty="Sender@X.com", subject="Re: Budget Q3",
                           kind="drafted", source="approve_draft")
    # original inbound email: from sender@x.com, subject "Budget Q3" → must match the 'Re:' draft
    h = es.is_handled(tmp_path, "sender@x.com", "Budget Q3")
    assert h and h["kind"] == "drafted"


def test_handled_map_keyed_by_counterparty_and_norm_subject(tmp_path):
    es.mark_handled(tmp_path, counterparty="a@x.com", subject="Fwd: Re: Deal", kind="drafted")
    m = es.get_handled_map(tmp_path)
    assert ("a@x.com", "deal") in m, f"normalized key expected, got {list(m)}"


def test_handled_unkeyable_is_noop(tmp_path):
    assert es.mark_handled(tmp_path, counterparty="", subject="x") is False
    assert es.mark_handled(tmp_path, counterparty="a@x.com", subject="Re:") is False  # empty after strip
    assert es.get_handled_map(tmp_path) == {}


def test_handled_reupsert_does_not_duplicate(tmp_path):
    es.mark_handled(tmp_path, counterparty="a@x.com", subject="Re: Deal", kind="drafted")
    es.mark_handled(tmp_path, counterparty="a@x.com", subject="RE: deal", kind="replied")  # same key
    m = es.get_handled_map(tmp_path)
    assert len(m) == 1 and m[("a@x.com", "deal")]["kind"] == "replied"


def test_overlay_handled_splits_items(tmp_path):
    es.mark_handled(tmp_path, counterparty="daniel.zhang@imodel3d.com",
                    subject="Re: MEP Ai Tools", kind="drafted")
    items = [
        {"email_id": "E1", "subject": "Re: MEP Ai Tools", "from_email": "Daniel.Zhang@imodel3d.com"},
        {"email_id": "E2", "subject": "Follow-up: Meeting", "from_email": "other@x.com"},
    ]
    kept, moved = es.overlay_handled(tmp_path, items)
    assert [k["email_id"] for k in kept] == ["E2"]
    assert [m["email_id"] for m in moved] == ["E1"]


def test_overlay_handled_noop_when_empty(tmp_path):
    items = [{"email_id": "E1", "subject": "X", "from_email": "a@x.com"}]
    kept, moved = es.overlay_handled(tmp_path, items)
    assert kept == items and moved == []


def test_prune_handled(tmp_path):
    es.mark_handled(tmp_path, counterparty="a@x.com", subject="Old", kind="drafted")
    # force the row's timestamp into the past, then prune
    con = es._conn(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    con.execute("UPDATE email_handled SET handled_at=?", (old,))
    con.commit()
    con.close()
    assert es.prune_handled(tmp_path, days=45) == 1
    assert es.get_handled_map(tmp_path) == {}
