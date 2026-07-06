"""The old weekly auto-merge silently fused DISTINCT projects (张冠李戴 — e.g. IPSC-Piping
folded into TransTech-MSA with zero shared people/topics). Every merge left a ledger entry
with before-snapshots, so splits are deterministic: re-judge old merges with today's features,
restore from the snapshots on approval. These guard the full lifecycle: detect → split
(surgical subtract, chained merges undo independently) → anti-resurrection → unsplit."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_split_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import db_cleaner as dc  # noqa: E402
from src.modules import projects_store  # noqa: E402


def _proj(pid, name, participants, topics, convs, threads=1):
    return {"id": pid, "name": name, "participants": participants, "key_topics": topics,
            "conversation_ids": convs, "thread_count": threads, "status": "ongoing"}


def _seed(data_dir, projects):
    projects_store.replace_from_dict(Path(data_dir), {"projects": {p["id"]: p for p in projects}})


def _load(data_dir):
    return projects_store.load_projects(Path(data_dir)).get("projects", {})


IPSC = _proj("ipsc-piping", "IPSC — Piping S3D Admin",
             ["amr@ipsc.com"], ["piping", "s3d", "admin"], ["c1", "c2"], 2)
TRANS = _proj("transtech-msa", "TransTech — MSA Finalization",
              ["lee@transtech.com"], ["msa", "legal", "contract"], ["c3"], 1)
# a LEGIT merge pair: same client, shared topic + person (fragments of one deliverable)
FRAG_A = _proj("acme-audit", "Acme Audit", ["bob@acme.com"], ["audit", "compliance"], ["c4"], 1)
FRAG_B = _proj("acme-audit-2", "Acme Audit Phase", ["bob@acme.com"], ["audit"], ["c5"], 1)


def test_wrong_merge_is_detected_and_split_restores_both(tmp_path):
    _seed(tmp_path, [IPSC, TRANS])
    r = dc.merge_projects(tmp_path, "transtech-msa", "ipsc-piping")   # the real incident shape
    assert r["ok"] and "ipsc-piping" not in _load(tmp_path)

    cands = dc.find_wrongly_merged_projects(tmp_path)
    assert len(cands) == 1 and cands[0]["type"] == "project_split"
    assert cands[0]["confidence"] == "high"
    assert {p["id"] for p in cands[0]["restore"]} == {"transtech-msa", "ipsc-piping"}

    r = dc.split_project(tmp_path, "transtech-msa", "ipsc-piping")
    assert r["ok"]
    projects = _load(tmp_path)
    assert "ipsc-piping" in projects                       # resurrected
    kept = projects["transtech-msa"]
    assert set(kept["conversation_ids"]) == {"c3"}          # merged-in threads subtracted
    assert "amr@ipsc.com" not in kept["participants"]
    assert kept["thread_count"] == 1
    # anti-resurrection marks on BOTH rows
    assert "ipsc-piping" in kept.get("distinct_from", [])
    assert "transtech-msa" in projects["ipsc-piping"].get("distinct_from", [])


def test_legit_merge_is_not_flagged(tmp_path):
    _seed(tmp_path, [FRAG_A, FRAG_B])
    dc.merge_projects(tmp_path, "acme-audit", "acme-audit-2")   # shares person + topic
    assert dc.find_wrongly_merged_projects(tmp_path) == []       # correct dedup stays merged


def test_split_survives_later_user_edits_on_kept_row(tmp_path):
    _seed(tmp_path, [IPSC, TRANS])
    dc.merge_projects(tmp_path, "transtech-msa", "ipsc-piping")
    # user renames the merged row AFTER the merge — the split must not clobber it
    projects_store.update_project_fields(tmp_path, "transtech-msa", {"name": "TransTech MSA (renamed)"})
    dc.split_project(tmp_path, "transtech-msa", "ipsc-piping")
    assert _load(tmp_path)["transtech-msa"]["name"] == "TransTech MSA (renamed)"


def test_unsplit_reverts_exactly(tmp_path):
    _seed(tmp_path, [IPSC, TRANS])
    dc.merge_projects(tmp_path, "transtech-msa", "ipsc-piping")
    merged_row = dict(_load(tmp_path)["transtech-msa"])
    dc.split_project(tmp_path, "transtech-msa", "ipsc-piping")
    r = dc.unsplit_project(tmp_path, "transtech-msa", "ipsc-piping")
    assert r["ok"]
    projects = _load(tmp_path)
    assert "ipsc-piping" not in projects                    # resurrected row removed again
    assert projects["transtech-msa"] == merged_row          # kept row back to pre-split state


def test_split_pair_never_reproposed_as_duplicate(tmp_path):
    _seed(tmp_path, [IPSC, TRANS])
    dc.merge_projects(tmp_path, "transtech-msa", "ipsc-piping")
    dc.split_project(tmp_path, "transtech-msa", "ipsc-piping")
    # distinct_from must gate dedup eligibility — ai=None proves no pair even reaches the judge
    cands = dc.find_duplicate_projects(tmp_path, ai=None)
    pair_ids = {(c["primary"]["id"], c["duplicate"]["id"]) for c in cands}
    assert ("transtech-msa", "ipsc-piping") not in pair_ids
    assert ("ipsc-piping", "transtech-msa") not in pair_ids


def test_already_restored_pair_yields_no_candidate(tmp_path):
    _seed(tmp_path, [IPSC, TRANS])
    dc.merge_projects(tmp_path, "transtech-msa", "ipsc-piping")
    dc.split_project(tmp_path, "transtech-msa", "ipsc-piping")
    assert dc.find_wrongly_merged_projects(tmp_path) == []   # merge_id exists again → skip


def test_chained_merges_each_undo_only_their_contribution(tmp_path):
    delco2 = _proj("delco-2", "Delco Water Phase 2", ["kim@delco.com"], ["phase2"], ["c6"], 1)
    delco3 = _proj("delco-3", "Delco Water Permits", ["raj@permits.com"], ["permits"], ["c7"], 1)
    base = _proj("delco", "Delco Water", ["ann@delco.ca"], ["water"], ["c8"], 1)
    _seed(tmp_path, [base, delco2, delco3])
    dc.merge_projects(tmp_path, "delco", "delco-2")
    dc.merge_projects(tmp_path, "delco", "delco-3")          # chained (the real Delco shape)
    r = dc.split_project(tmp_path, "delco", "delco-3")       # undo ONLY the second merge
    assert r["ok"]
    projects = _load(tmp_path)
    kept = projects["delco"]
    assert "c7" not in kept["conversation_ids"]              # delco-3's thread removed
    assert "c6" in kept["conversation_ids"]                  # delco-2's contribution untouched
    assert "delco-3" in projects and "delco-2" not in projects
