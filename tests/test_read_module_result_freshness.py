"""The recurring bug: sections bake status:"fresh" at write time and read_module_result served
that forever — a 3-day-old meetings_today cache shown as today's meetings (Kimi read it faithfully).
Systemic fix: meetings_today is fetched LIVE; every other cached section has its status recomputed
from last_run/date at read time. These guard: live-not-cache, stale-flagged, date-anchor, and no
false stale on fresh data. Mirrors tests/test_read_module_result_projects.py."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_rmr_fresh_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot_tools.sections.read_module_result.tool import build  # noqa: E402


class FakeGraph:
    def __init__(self, events):
        self.events = events
        self.called = False

    def get_calendar_view(self, start_dt, end_dt, top=50):
        self.called = True
        return self.events


def _ctx(tmp_path, graph=None):
    return SimpleNamespace(data_dir=tmp_path, settings={"timezone": "UTC"}, state={}, owner_graph=graph)


def _read(tmp_path, section, graph=None):
    return json.loads(build(_ctx(tmp_path, graph))(section))


def _write_result(tmp_path, section, obj):
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / f"{section}.json").write_text(json.dumps(obj))


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ── meetings_today: LIVE, never the cache ────────────────────────────────────
def test_meetings_today_is_live_not_stale_cache(tmp_path):
    # a stale cache with a ghost meeting from 3 days ago must be ignored
    _write_result(tmp_path, "meetings_today", {
        "id": "meetings_today", "status": "fresh", "date": "2026-07-04", "last_run": _iso(3),
        "items": [{"id": "ghost", "subject": "Ghost Weekly Catch-up", "start_time": "10:30"}], "count": 1})
    ev = [{"id": "e1", "subject": "Real Standup", "start": {"dateTime": "2026-07-07T15:00:00"},
           "end": {"dateTime": "2026-07-07T15:30:00"}, "attendees": []}]
    g = FakeGraph(ev)
    data = _read(tmp_path, "meetings_today", graph=g)
    assert g.called                                   # it did a LIVE calendar fetch
    assert data["status"] == "fresh"
    subjects = {it["subject"] for it in data["items"]}
    assert subjects == {"Real Standup"} and "Ghost Weekly Catch-up" not in subjects


def test_meetings_today_live_empty(tmp_path):
    _write_result(tmp_path, "meetings_today", {"id": "meetings_today", "status": "fresh",
                  "date": "2026-07-04", "last_run": _iso(3), "items": [{"subject": "Ghost"}], "count": 1})
    data = _read(tmp_path, "meetings_today", graph=FakeGraph([]))
    assert data["items"] == [] and data["empty"] is True and data["status"] == "fresh"


# ── systemic staleness: cached sections recompute status from last_run/date ──
def test_expensive_section_old_cache_is_marked_stale(tmp_path):
    _write_result(tmp_path, "market_intelligence", {
        "id": "market_intelligence", "status": "fresh", "last_run": _iso(10),
        "items": [{"id": "x", "title": "old signal"}], "count": 1})
    data = _read(tmp_path, "market_intelligence")
    assert data["status"] == "stale" and data.get("as_of")     # honestly flagged, not "fresh"
    assert data["items"]                                       # items still returned (with the flag)


def test_recent_cache_stays_fresh(tmp_path):
    _write_result(tmp_path, "reply_needed", {
        "id": "reply_needed", "status": "fresh", "last_run": _iso(0),   # ran today
        "items": [], "count": 0})
    assert _read(tmp_path, "reply_needed")["status"] == "fresh"


def test_yesterday_recap_wrong_date_is_stale(tmp_path):
    _write_result(tmp_path, "yesterday_recap", {
        "id": "yesterday_recap", "status": "fresh", "last_run": _iso(3),
        "date": "2026-07-01", "items": [{"x": 1}], "count": 1})     # date is days off, not "yesterday"
    assert _read(tmp_path, "yesterday_recap")["status"] == "stale"


def test_missing_last_run_does_not_falsely_flag(tmp_path):
    _write_result(tmp_path, "business_insights", {
        "id": "business_insights", "status": "fresh", "items": [], "count": 0})   # no last_run
    assert _read(tmp_path, "business_insights")["status"] == "fresh"   # unknown age → don't cry wolf


def test_never_run_section_reports_not_run(tmp_path):
    out = build(_ctx(tmp_path))("company_intelligence")
    assert "No results" in out
