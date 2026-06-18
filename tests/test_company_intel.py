"""Unit tests for the company_intelligence-specific integration:
per-company top-K quota (no tracked company zeroed, anti-domination) and
per-company enrichment selection. Plus the materiality scoring mode on
intel_score. No network, no real AI.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sections.company_intelligence import (  # noqa: E402
    _apply_company_quota, _select_for_enrichment, _PER_COMPANY_CAP, _MAX_ITEMS,
)
from src.modules import intel_score  # noqa: E402


def _scored(spec):
    """spec: {company: [scores...]} -> flat list sorted by score desc."""
    items = []
    for co, scores in spec.items():
        for s in scores:
            items.append({"company": co, "ai_score": float(s), "headline": f"{co} {s}"})
    items.sort(key=lambda x: x["ai_score"], reverse=True)
    return items


def test_quota_zeroes_no_tracked_company():
    # Microsoft dominates on score; Stantec is low — must NOT be dropped.
    items = _scored({"Microsoft": [10, 9, 9, 8, 8, 7, 6], "Stantec": [5, 4], "Accenture": [8, 6]})
    kept = _apply_company_quota(items)
    counts = Counter(i["company"] for i in kept)
    assert counts["Stantec"] >= 1            # the whole point: tracked company retained
    assert counts["Microsoft"] <= _PER_COMPANY_CAP
    assert all(c <= _PER_COMPANY_CAP for c in counts.values())
    assert len(kept) <= _MAX_ITEMS


def test_quota_global_cap_still_keeps_every_company_first():
    # Many companies, each 1 item; round-robin must keep them all under the cap.
    items = _scored({f"Co{i}": [9 - i * 0.1] for i in range(min(_MAX_ITEMS, 10))})
    kept = _apply_company_quota(items)
    assert len(set(i["company"] for i in kept)) == len(set(i["company"] for i in items))


def test_enrichment_selection_distributes_across_companies():
    items = _scored({"Microsoft": [10, 9, 9], "Stantec": [6, 5], "Accenture": [8, 7]})
    sel = _select_for_enrichment(items)
    co = set(i["company"] for i in sel)
    assert co == {"Microsoft", "Stantec", "Accenture"}   # not monopolized by Microsoft
    # selection returns references into the list (so enrich updates in place)
    assert all(any(s is it for it in items) for s in sel)


class _FakeScoreAI:
    def extract_json(self, prompt: str) -> str:
        n = len(re.findall(r"^\[\d+\]", prompt, re.M))
        return json.dumps([{"index": i + 1, "score": 7, "reason": "x"} for i in range(n)])


def test_materiality_mode_scores_without_gate():
    items = [{"company": "Stantec", "headline": "Stantec JV", "summary": "s", "signal_type": "announcement"}]
    out = intel_score.score_items(items, _FakeScoreAI(), purpose="materiality")
    assert out[0]["ai_score"] == 7.0 and out[0]["priority"] == "medium"
