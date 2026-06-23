"""Unit tests for the commitments SQLite store (Phase 1 of the single-store migration)."""
import json
from datetime import date, timedelta

from src.modules import commitments_store as store


def _seed(d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps({"display_name": "T", "timezone": "America/Edmonton"}))


def _item(i, **kw):
    base = {"id": i, "type": "my_commitment", "description": f"desc {i}",
            "due_date": None, "priority": "medium", "email_id": f"M{i}"}
    base.update(kw)
    return base


def _vis(d):
    return {x["id"] for x in store.query_visible(d)}


def test_upsert_preserves_status_on_reextraction(tmp_path):
    _seed(tmp_path)
    store.upsert_commitments(tmp_path, [_item("a"), _item("b")])
    store.mark_done(tmp_path, "a")
    assert _vis(tmp_path) == {"b"}
    # Re-extraction with changed content must NOT resurrect a done item.
    store.upsert_commitments(tmp_path, [_item("a", description="changed"), _item("b")])
    assert _vis(tmp_path) == {"b"}, "done status must survive re-upsert"


def test_mark_done_and_dismiss_hide(tmp_path):
    _seed(tmp_path)
    store.upsert_commitments(tmp_path, [_item("a"), _item("b"), _item("c")])
    store.mark_done(tmp_path, "a")
    store.mark_dismissed(tmp_path, "b")
    assert _vis(tmp_path) == {"c"}


def test_snooze_hides_then_resurfaces(tmp_path):
    _seed(tmp_path)
    store.upsert_commitments(tmp_path, [_item("a")])
    store.mark_snoozed(tmp_path, "a", days=2)
    today = date.today().isoformat()
    assert "a" not in {x["id"] for x in store.query_visible(tmp_path, today)}
    future = (date.today() + timedelta(days=5)).isoformat()
    assert "a" in {x["id"] for x in store.query_visible(tmp_path, future)}, "snooze should expire"


def test_expire_asked_moves_to_done(tmp_path):
    _seed(tmp_path)
    store.upsert_commitments(tmp_path, [_item("a")])
    store.mark_asked(tmp_path, "a", expire_hours=24)
    assert "a" not in _vis(tmp_path), "an actively-asked item is hidden"
    # force the asked window into the past, then expire
    store.mark_asked(tmp_path, "a", expire_hours=-48)
    expired = store.expire_asked(tmp_path)
    assert "a" in expired and "a" not in _vis(tmp_path)


def test_mark_done_by_email_id(tmp_path):
    _seed(tmp_path)
    store.upsert_commitments(tmp_path, [_item("a", email_id="MX"), _item("b", email_id="MX"), _item("c")])
    n = store.mark_done_by_email_id(tmp_path, "MX")
    assert n == 2 and _vis(tmp_path) == {"c"}


def test_due_today_and_upcoming(tmp_path):
    _seed(tmp_path)
    today = date.today().isoformat()
    tmrw = (date.today() + timedelta(days=1)).isoformat()
    yday = (date.today() - timedelta(days=1)).isoformat()
    far = (date.today() + timedelta(days=30)).isoformat()
    store.upsert_commitments(tmp_path, [
        _item("t", due_date=today), _item("u", due_date=tmrw),
        _item("o", due_date=yday), _item("far", due_date=far),
        _item("their", type="their_commitment", due_date=today)])
    due = {x["id"] for x in store.query_due_today(tmp_path, today)}
    assert due == {"t"}, "due_today: my_commitment due today only"
    cutoff = (date.today() + timedelta(days=7)).isoformat()
    up = {x["id"] for x in store.query_upcoming(tmp_path, today, cutoff)}
    assert up == {"t", "u", "o"}, "upcoming: my_commitment due<=cutoff incl. overdue, excl. far"


def test_import_does_not_resurrect_gone_snoozed(tmp_path):
    """A snoozed/asked id NOT in the extract snapshot must not become a blank visible row.
    (Real-account migration bug: expired snoozes of gone commitments resurfaced as empty items.)"""
    _seed(tmp_path)
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "commitments_extract.json").write_text(json.dumps({"items": [_item("a")]}))
    past = (date.today() - timedelta(days=5)).isoformat()  # an EXPIRED snooze
    (tmp_path / "commitments_state.json").write_text(json.dumps({
        "done": {}, "asked": {}, "snoozed": {"gone1": {"until": past}}}))
    assert _vis(tmp_path) == {"a"}, "a gone snoozed id must not resurrect as a blank row"


def test_import_from_json_idempotent(tmp_path):
    _seed(tmp_path)
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "commitments_extract.json").write_text(json.dumps({
        "items": [_item("a"), _item("b"), _item("c")]}))
    (tmp_path / "commitments_state.json").write_text(json.dumps({
        "done": {"a": {"at": "2026-01-01", "method": "user"}}, "asked": {}, "snoozed": {}}))
    (tmp_path / "commitments_cache.json").write_text(json.dumps({
        "emails": {"M1": {"received": "2026-06-01", "commitments": [{"description": "x"}], "msg_meta": {}}}}))
    # first access triggers the one-time import
    assert _vis(tmp_path) == {"b", "c"}, "imported done status (a) is hidden"
    assert "M1" in store.get_processed_ids(tmp_path)
    # idempotent: importing again must not double or resurrect
    store.upsert_commitments(tmp_path, [])  # touches the store again
    assert _vis(tmp_path) == {"b", "c"}
