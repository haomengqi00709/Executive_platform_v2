"""Merge-detection must NOT treat a shared company NAME alone as a duplicate — one company can
run multiple distinct projects (the 张冠李戴 case Daniel hit). Eligibility now requires ≥1 shared
participant OR topic to corroborate a name/entity match before a pair even reaches the AI judge.
This path was previously untested; these are the regression net."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_dc_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import db_cleaner as dc  # noqa: E402


class StubAI:
    """Records how many pairs reached the AI judge + returns a fixed verdict."""
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def extract_json(self, prompt):
        self.calls += 1
        return json.dumps(self.verdict)


def _seed(d, projects):
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / "projects.json").write_text(json.dumps({"projects": {p["id"]: p for p in projects}}))


def _proj(pid, name, participants=(), topics=()):
    return {"id": pid, "name": name, "participants": list(participants), "key_topics": list(topics),
            "summary": "", "status": "ongoing", "conversation_ids": [], "ignore": False, "archived": False}


# ── same company, different deliverables, nothing shared → NOT a candidate ────

def test_same_company_zero_shared_is_not_a_candidate(tmp_path):
    _seed(tmp_path, [
        _proj("diar-tender", "Diar Group — Tender Proposal", ["alice@diar.com"], ["tender", "pricing"]),
        _proj("diar-pid",    "Diar Group — P&ID Conversion", ["bob@diar.com"],   ["pid", "conversion"]),
    ])
    ai = StubAI({"is_duplicate": True, "confidence": "high", "reasoning": "x"})
    cands = dc.find_duplicate_projects(tmp_path, ai)
    assert ai.calls == 0, "same company + 0 shared people + 0 shared topics must never reach the AI judge"
    assert cands == []


# ── corroborated by a shared topic → IS a candidate ──────────────────────────

def test_same_company_shared_topic_is_corroborated_candidate(tmp_path):
    _seed(tmp_path, [
        _proj("diar-a", "Diar Group — Tender A", ["alice@diar.com"], ["tender", "pricing"]),
        _proj("diar-b", "Diar Group — Tender B", ["bob@diar.com"],   ["tender", "bid"]),
    ])
    ai = StubAI({"is_duplicate": True, "confidence": "medium", "reasoning": "same tender"})
    cands = dc.find_duplicate_projects(tmp_path, ai)
    assert ai.calls == 1                          # 1 shared topic corroborates → judged
    assert len(cands) == 1


# ── shared participants (the classic dup) → IS a candidate ───────────────────

def test_shared_participants_is_a_candidate(tmp_path):
    _seed(tmp_path, [
        _proj("a", "Acme Audit",             ["cfo@acme.com", "ops@acme.com"], ["audit"]),
        _proj("b", "Acme Audit Remediation", ["cfo@acme.com", "ops@acme.com"], ["audit"]),
    ])
    ai = StubAI({"is_duplicate": True, "confidence": "high", "reasoning": "same audit"})
    cands = dc.find_duplicate_projects(tmp_path, ai)
    assert ai.calls == 1
    assert len(cands) == 1 and cands[0]["confidence"] == "high"


# ── AI says distinct → no candidate even when eligible ───────────────────────

def test_ai_distinct_verdict_yields_no_candidate(tmp_path):
    _seed(tmp_path, [
        _proj("a", "Acme Strategy",       ["cfo@acme.com", "ops@acme.com"], ["strategy"]),
        _proj("b", "Acme Financial Model", ["cfo@acme.com", "ops@acme.com"], ["strategy"]),
    ])
    ai = StubAI({"is_duplicate": False, "confidence": "low", "reasoning": "different deliverables"})
    cands = dc.find_duplicate_projects(tmp_path, ai)
    assert ai.calls == 1 and cands == []
