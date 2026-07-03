"""The refresh fold used to merge any two clusters sharing ≥2 people — conflating a company's
distinct projects (张冠李戴). It now also requires TOPIC similarity. These guard the topic signal:
same-deliverable → fold; same-people-different-deliverable → NOT auto-folded (kept separate)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_fold_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects as pj  # noqa: E402


def _p(name, topics):
    return {"name": name, "key_topics": list(topics)}


# ── the core 张冠三李戴 unit: same company/people, different deliverable → not auto-folded ──

def test_same_company_distinct_deliverables_not_autofolded():
    tender = _p("Diar — Tender Proposal", ["tender", "pricing", "bid", "proposal"])
    conv   = _p("Diar — P&ID Conversion", ["conversion", "drawings", "cad", "asbuilt"])
    sim = pj._topic_similarity(tender, conv)
    assert sim < pj._FOLD_TOPIC_SIM, f"distinct deliverables must not deterministically fold (sim={sim:.2f})"


def test_same_deliverable_folds():
    a = _p("Acme Audit", ["audit", "compliance", "remediation"])
    b = _p("Acme Audit Remediation", ["audit", "remediation", "compliance"])
    assert pj._topic_similarity(a, b) >= pj._FOLD_TOPIC_SIM   # same work → fold


def test_topic_tokens_drop_generic_and_scheduling_noise():
    toks = pj._topic_tokens(_p("The Strategy Project", ["meeting", "scheduling", "nexus", "capital"]))
    assert "nexus" in toks and "capital" in toks
    assert not ({"meeting", "scheduling", "strategy", "the", "project"} & toks)


def test_empty_topics_is_zero_similarity_safe():
    # no distinctive tokens either side → 0.0 → keep separate (safe; duplicates are catchable by cleaning)
    assert pj._topic_similarity(_p("", []), _p("Acme", ["audit"])) == 0.0


# ── the split anti-resurrection marker ───────────────────────────────────────

def test_are_marked_distinct_is_symmetric():
    a = {"id": "diar-2", "distinct_from": ["diar"]}
    b = {"id": "diar"}
    assert pj._are_marked_distinct(a, b) is True
    assert pj._are_marked_distinct(b, a) is True
    assert pj._are_marked_distinct(a, {"id": "other"}) is False


def test_fold_into_unions_threads():
    ex = {"conversation_ids": ["c1", "c2"]}
    pj._fold_into(ex, {"conversation_ids": ["c2", "c3"]})
    assert ex["conversation_ids"] == ["c1", "c2", "c3"] and ex["thread_count"] == 3
