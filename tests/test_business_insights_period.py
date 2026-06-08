"""Weekly report (business_insights) aligned-week period.

Covers the 2026-06 Daniel bug: the weekly report showed last week's meetings
under a "this week" label because each source used its own 14/21-day window.
Now everything is filtered to ONE complete Mon–Sun week (user tz), with a
retrospective / now / week-ahead split.
"""
import json
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path

os.environ.setdefault("PROD_CLIENT_ID", "test-cid")
os.environ.setdefault("PROD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sections import business_insights as bi  # noqa: E402


class _StubAI:
    def generate(self, prompt):
        return "Stub weekly narrative."


def _write(data_dir, section, obj):
    p = Path(data_dir) / "results" / f"{section}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


# ── _last_complete_week (the "which week" fix) ───────────────────────────────

def test_last_complete_week_monday(monkeypatch, tmp_path):
    # Run Monday Jun 8 → covers the week that just ended, Jun 1–7.
    monkeypatch.setattr(bi, "now_local", lambda d: datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc))
    assert bi._last_complete_week(tmp_path) == (date(2026, 6, 1), date(2026, 6, 7))


def test_last_complete_week_midweek(monkeypatch, tmp_path):
    # Run Wednesday Jun 10 → still the last fully-ended week, Jun 1–7.
    monkeypatch.setattr(bi, "now_local", lambda d: datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc))
    assert bi._last_complete_week(tmp_path) == (date(2026, 6, 1), date(2026, 6, 7))


def test_last_complete_week_sunday(monkeypatch, tmp_path):
    # Run Sunday Jun 7 (current week not yet over) → the week before, May 25–31.
    monkeypatch.setattr(bi, "now_local", lambda d: datetime(2026, 6, 7, 9, 0, tzinfo=timezone.utc))
    assert bi._last_complete_week(tmp_path) == (date(2026, 5, 25), date(2026, 5, 31))


# ── _filter_by_period (inclusive boundaries) ─────────────────────────────────

def test_filter_by_period_inclusive():
    items = [{"d": "2026-06-01"}, {"d": "2026-06-07"}, {"d": "2026-05-31"},
             {"d": "2026-06-08"}, {"d": ""}, {"d": "2026-06-04T12:00:00Z"}]
    out = bi._filter_by_period(items, date(2026, 6, 1), date(2026, 6, 7), "d")
    assert [i["d"] for i in out] == ["2026-06-01", "2026-06-07", "2026-06-04T12:00:00Z"]


# ── _meetings_in_period (robust to missing recent_meetings.json) ─────────────

def test_meetings_prefer_recent_meetings():
    sources = {"recent_meetings": {"items": [{"title": "A", "date": "2026-06-03"}]},
               "meeting_action_items": {"items": []}}
    out = bi._meetings_in_period(sources, date(2026, 6, 1), date(2026, 6, 7))
    assert len(out) == 1 and out[0]["title"] == "A"


def test_meetings_derived_when_recent_missing():
    # Daniel's case: recent_meetings.json absent → derive distinct meetings from
    # meeting_action_items (same wiki data).
    sources = {"recent_meetings": {}, "meeting_action_items": {"items": [
        {"meeting_id": "m1", "meeting_title": "weekly meeting", "meeting_date": "2026-06-02"},
        {"meeting_id": "m1", "meeting_title": "weekly meeting", "meeting_date": "2026-06-02"},
        {"meeting_id": "m2", "meeting_title": "AI 3D", "meeting_date": "2026-06-05"},
        {"meeting_id": "m0", "meeting_title": "old", "meeting_date": "2026-05-20"},  # outside
    ]}}
    out = bi._meetings_in_period(sources, date(2026, 6, 1), date(2026, 6, 7))
    assert len(out) == 2  # m1, m2 distinct; m0 outside period excluded


# ── end-to-end: Daniel-like snapshot ─────────────────────────────────────────

def test_end_to_end_daniel(monkeypatch, tmp_path):
    monkeypatch.setattr(bi, "now_local", lambda d: datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc))
    # recent_meetings.json MISSING; meeting_action_items has 3 meetings (18 items)
    # in Jun 1–7 + one older meeting outside the period.
    mai = (
        [{"meeting_id": "m1", "meeting_title": "weekly meeting", "meeting_date": "2026-06-02", "action": "x"}] * 10 +
        [{"meeting_id": "m2", "meeting_title": "AI 3D modelling intro", "meeting_date": "2026-06-04", "action": "y"}] * 5 +
        [{"meeting_id": "m3", "meeting_title": "AI 3D model intro", "meeting_date": "2026-06-05", "action": "z"}] * 3 +
        [{"meeting_id": "m0", "meeting_title": "old", "meeting_date": "2026-05-20", "action": "old"}]
    )
    _write(tmp_path, "meeting_action_items", {"items": mai, "count": len(mai)})
    _write(tmp_path, "reply_needed", {"items": [{"subject": "Potential client list from Bruce",
                                                  "from_name": "Bruce", "received": "2026-06-06",
                                                  "priority": "medium"}], "count": 1})
    _write(tmp_path, "followup_needed", {"items": [{"subject": "Follow up", "to_name": "x",
                                                     "sent": "2026-06-03"}], "count": 16})
    _write(tmp_path, "upcoming_commitments", {"items": [
        {"description": "Meeting with Thailand partner", "due_date": "2026-06-11"},
        {"description": "Meeting with David from UK", "due_date": "2026-06-12"},
    ], "count": 2})

    res = bi.run(None, _StubAI(), tmp_path, {"display_name": "Daniel"})

    assert res["period_start"] == "2026-06-01"
    assert res["period_end"] == "2026-06-07"
    assert res["period_label"].startswith("Jun 1")

    tw = res["stats"]["this_week"]
    assert tw["meetings_recent"] == 3          # 3 distinct in-period meetings (m0 excluded)
    assert tw["action_items_open"] == 18       # 18 in-period action items
    assert tw["emails_followup_needed"] == 16  # current backlog — NOT period-filtered
    assert tw["commitments_due_this_week"] == 2  # forward (Jun 11/12 within Jun 8..15)

    by_tf = {}
    for h in res["items"]:
        by_tf.setdefault(h["timeframe"], []).append(h["title"])
    meet = [t for t in by_tf.get("past", []) if "meeting(s) this week" in t]
    com = [t for t in by_tf.get("ahead", []) if "due in the next 7 days" in t]
    fup = [t for t in by_tf.get("now", []) if "sent without a reply" in t]
    assert meet, "meeting headline should be in 'past'"
    assert com, "commitments-due headline should be in 'ahead'"
    assert fup, "followup headline should be in 'now'"
