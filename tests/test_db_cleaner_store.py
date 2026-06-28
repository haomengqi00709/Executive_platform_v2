"""db_cleaner now persists merges/archives through the SQLite store, not direct JSON writes.

THE headline guarantee: after a merge/archive, the change lives in the store — so a later refresh
(which regenerates projects.json/crm.json FROM the store) can't resurrect a merged-away duplicate or
undo an archive. Before this fix, db_cleaner wrote the JSON directly while the store kept the old rows,
so the next refresh rolled the cleanup back."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_dbclean_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects_store as ps      # noqa: E402
from src.modules import crm_store as cs            # noqa: E402
from src.modules import db_cleaner                 # noqa: E402


def _proj(pid, **kw):
    base = {"id": pid, "name": pid, "participants": [], "conversation_ids": [], "key_topics": [],
            "thread_count": 0, "status": "ongoing", "ignore": False, "last_activity": "2026-06-01"}
    base.update(kw)
    return base


def _contact(email, **kw):
    base = {"email": email, "name": email, "thread_count": 0, "status": "other"}
    base.update(kw)
    return base


# ── project merge ─────────────────────────────────────────────────────────────

def test_merge_projects_persists_in_store_no_resurrection(tmp_path):
    ps.replace_from_dict(tmp_path, {"last_scan": "x", "projects": {
        "keep": _proj("keep", participants=["a@x.com"], conversation_ids=["c1"], key_topics=["t1"],
                      thread_count=2, ignore=True, last_activity="2026-06-10"),
        "dup":  _proj("dup", participants=["b@x.com"], conversation_ids=["c2"], key_topics=["t2"],
                      thread_count=3, last_activity="2026-06-20")}})

    r = db_cleaner.merge_projects(tmp_path, "keep", "dup")
    assert r["ok"] and r["removed_id"] == "dup"

    out = ps.load_projects(tmp_path)["projects"]
    assert "dup" not in out, "duplicate must be gone from the STORE (not just the JSON)"
    keep = out["keep"]
    assert set(keep["participants"]) == {"a@x.com", "b@x.com"}      # unioned
    assert set(keep["conversation_ids"]) == {"c1", "c2"}
    assert keep["thread_count"] == 5
    assert keep["last_activity"] == "2026-06-20"                     # later wins
    assert keep["ignore"] is True                                    # user column preserved

    # THE rollback test: regenerate the projection from the store (what a refresh does) →
    # the merged-away duplicate must NOT come back.
    ps.write_projection(tmp_path)
    proj = json.loads((tmp_path / "projects.json").read_text())["projects"]
    assert "dup" not in proj and "keep" in proj


def test_merge_projects_missing_returns_error(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {"keep": _proj("keep")}})
    assert db_cleaner.merge_projects(tmp_path, "keep", "ghost")["ok"] is False


# ── project archive ───────────────────────────────────────────────────────────

def test_archive_project_persists_in_store(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {"p1": _proj("p1", archived=False)}})
    r = db_cleaner.archive_record(tmp_path, "project", "p1")
    assert r["ok"]
    assert ps.load_projects(tmp_path)["projects"]["p1"]["archived"] is True
    ps.write_projection(tmp_path)                                   # survives a refresh
    assert json.loads((tmp_path / "projects.json").read_text())["projects"]["p1"]["archived"] is True
    assert db_cleaner.archive_record(tmp_path, "project", "ghost")["ok"] is False


# ── contact merge / archive (CRM had the same hole) ───────────────────────────

def test_merge_contacts_persists_in_store_no_resurrection(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {
        "keep@x.com": _contact("keep@x.com", thread_count=2, tags=["vip"], company=""),
        "dup@x.com":  _contact("dup@x.com", thread_count=3, company="Acme")}})

    r = db_cleaner.merge_contacts(tmp_path, "keep@x.com", "dup@x.com")
    assert r["ok"] and r["removed_email"] == "dup@x.com"

    out = cs.load_crm(tmp_path)["contacts"]
    assert "dup@x.com" not in out, "duplicate must be gone from the STORE"
    keep = out["keep@x.com"]
    assert keep["thread_count"] == 5
    assert keep["company"] == "Acme"                                # filled from merge (keep was empty)
    assert keep["tags"] == ["vip"]                                  # user column preserved
    assert "dup@x.com" in keep["aliases"]                           # alias tracked

    cs.write_projection(tmp_path)
    proj = json.loads((tmp_path / "crm.json").read_text())["contacts"]
    assert "dup@x.com" not in proj and "keep@x.com" in proj


def test_merge_contacts_is_lossless_union(tmp_path):
    """Merge must STACK both sides' data, never overwrite: the merged-away contact's tags / notes /
    priority / ignore survive, its email + name become alias/variant — nothing the user set is lost."""
    cs.replace_from_dict(tmp_path, {"contacts": {
        "keep@x.com": _contact("keep@x.com", name="Jason Hao", thread_count=2,
                               tags=["vip"], priority="low", notes="from keep", company="Acme"),
        "dup@x.com":  _contact("dup@x.com", name="Hao Jason", thread_count=3,
                               tags=["client"], priority="high", notes="from dup",
                               ignore=True, company="Globex")}})

    r = db_cleaner.merge_contacts(tmp_path, "keep@x.com", "dup@x.com")
    assert r["ok"]

    keep = cs.load_crm(tmp_path)["contacts"]["keep@x.com"]
    assert sorted(keep["tags"]) == ["client", "vip"]                      # tags UNIONED, dup's kept
    assert keep["priority"] == "high"                                     # stronger priority wins
    assert keep["ignore"] is True                                         # dup's ignore flag survives
    assert "from keep" in keep["notes"] and "from dup" in keep["notes"]   # both notes kept
    assert keep["thread_count"] == 5                                      # counts summed
    assert "dup@x.com" in keep["aliases"]                                 # merged email kept as alias
    assert "Hao Jason" in keep.get("name_variants", [])                  # merged name kept as variant
    assert keep["company"] == "Acme" and "Globex" in keep["notes"]       # primary kept, other recorded
    assert "dup@x.com" not in cs.load_crm(tmp_path)["contacts"]          # duplicate row gone


def test_archive_contact_persists_in_store(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {"c@x.com": _contact("c@x.com", tags=["keep"])}})
    r = db_cleaner.archive_record(tmp_path, "contact", "c@x.com")
    assert r["ok"]
    c = cs.load_crm(tmp_path)["contacts"]["c@x.com"]
    assert c["archived"] is True and c["tags"] == ["keep"]          # flag set, user col preserved
    assert db_cleaner.archive_record(tmp_path, "contact", "ghost@x.com")["ok"] is False


# ── approve_candidates end-to-end (delegates to the routed functions) ─────────

def test_approve_candidates_routes_through_store(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {
        "keep": _proj("keep", participants=["a@x.com"]),
        "dup":  _proj("dup", participants=["a@x.com"])}})
    db_cleaner.save_pending(tmp_path, [{
        "id": "cand1", "type": "project_duplicate",
        "primary": {"id": "keep"}, "duplicate": {"id": "dup"}, "confidence": "high"}])
    counts = db_cleaner.approve_candidates(tmp_path, ["cand1"])
    assert counts["merged_projects"] == 1
    assert "dup" not in ps.load_projects(tmp_path)["projects"]
