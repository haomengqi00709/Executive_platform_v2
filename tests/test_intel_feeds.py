"""Unit tests for the Horizon-derived market_intelligence additions:
intel_score (0-10 scoring + priority bands + fail-safe), feeds_config
(load/save/preset merge), and feeds_fetch RSS parsing. No network, no real AI.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import intel_score  # noqa: E402
from src.modules import feeds_config  # noqa: E402
from src.modules import feeds_fetch  # noqa: E402


class _FakeScoreAI:
    """Returns descending scores 9,7,3 cycling, one per [n] item in the prompt."""
    def extract_json(self, prompt: str) -> str:
        n = len(re.findall(r"^\[\d+\]", prompt, re.M))
        scores = [9, 7, 3]
        return json.dumps([
            {"index": i + 1, "score": scores[i % 3], "reason": f"r{i+1}"}
            for i in range(n)
        ])


class _RaiseAI:
    def extract_json(self, prompt: str) -> str:
        raise RuntimeError("AI down")


def _items(n):
    return [{"headline": f"H{i}", "summary": f"S{i}", "signal_type": "other", "source": "x"} for i in range(n)]


def test_score_attaches_and_sorts_and_buckets():
    items = intel_score.score_items(_items(3), _FakeScoreAI(), reader_context="ctx", instruction="inst")
    scores = [it["ai_score"] for it in items]
    assert scores == [9.0, 7.0, 3.0]            # sorted descending
    assert items[0]["priority"] == "high"        # >= 8
    assert items[1]["priority"] == "medium"      # >= 6
    assert items[2]["priority"] == "low"         # < 6
    assert all(it["score_reason"] for it in items)


def test_score_failsafe_keeps_items_at_threshold():
    items = intel_score.score_items(_items(2), _RaiseAI())
    assert all(it["ai_score"] == intel_score.DEFAULT_THRESHOLD for it in items)
    assert all(it["priority"] == "medium" for it in items)  # threshold maps to medium


def test_coerce_score_does_not_swallow_zero():
    assert intel_score._coerce_score(0) == 0.0     # a real 0 must survive (not None)
    assert intel_score._coerce_score("abc") is None
    assert intel_score._coerce_score(15) == 10.0   # clamped
    assert intel_score._coerce_score(-3) == 0.0


def test_feeds_default_and_roundtrip(tmp_path):
    cfg = feeds_config.load_feeds(tmp_path)
    assert cfg["enabled"] is False and cfg["rss"] == []   # disabled default when absent
    cfg["enabled"] = True
    cfg["rss"].append({"name": "A", "url": "https://a.com/feed", "enabled": True})
    feeds_config.save_feeds(tmp_path, cfg)
    again = feeds_config.load_feeds(tmp_path)
    assert again["enabled"] is True and again["rss"][0]["url"] == "https://a.com/feed"


def test_apply_preset_merges_and_dedupes(tmp_path):
    presets = feeds_config.load_presets()
    assert "ai_governance" in presets                      # repo presets load
    cfg = feeds_config.apply_preset(feeds_config.default_feeds(), "ai_governance")
    assert cfg["enabled"] is True and len(cfg["google_news"]) > 0
    n_before = len(cfg["google_news"])
    cfg = feeds_config.apply_preset(cfg, "ai_governance")   # idempotent
    assert len(cfg["google_news"]) == n_before


_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Hello &amp; World</title><link>https://ex.com/a</link>
<description>&lt;p&gt;Body &lt;b&gt;text&lt;/b&gt;&lt;/p&gt;</description>
<pubDate>Mon, 16 Jun 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_feed_bytes_cleans_and_dates():
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    items = feeds_fetch._parse_feed_bytes(_RSS, "Test", since)
    assert len(items) == 1
    it = items[0]
    assert it["headline"] == "Hello & World"
    assert it["summary"] == "Body text"               # HTML stripped + unescaped
    assert it["source_url"] == "https://ex.com/a"
    assert it["published_date"] == "2026-06-16"
    assert it["signal_type"] == "other"               # pre-scoring


def test_parse_feed_bytes_recency_filter():
    future_since = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert feeds_fetch._parse_feed_bytes(_RSS, "Test", future_since) == []


def test_fetch_feed_items_disabled_returns_empty():
    assert feeds_fetch.fetch_feed_items({"enabled": False}, datetime.now(timezone.utc)) == []
