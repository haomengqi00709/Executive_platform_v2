"""Unit tests for the CRM SQLite store (Phase 3a). The headline tests guard Daniel's
customizations: lossless migration + edit-preserving upsert that survives a concurrent edit."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_crm_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import crm_store as cs  # noqa: E402


def _seed_crm(d, contacts, last_scan="2026-06-20T00:00:00Z", months=6):
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / "crm.json").write_text(json.dumps(
        {"last_scan": last_scan, "months_scanned": months, "contacts": contacts}))


def _contact(**kw):
    base = {"email": "a@x.com", "name": "Alice", "company": "OldCo", "role": "",
            "status": "prospect", "summary": "", "writing_style": "",
            "thread_count": 1, "last_contact": "2026-06-01"}
    base.update(kw)
    return base


# ── lazy migration is lossless ───────────────────────────────────────────────

def test_migration_lossless_all_fields(tmp_path):
    c = _contact(notes="[2026-06-01] met at summit", tags=["investors", "vip"],
                 priority="high", ignore=True, archived=False, manual=True,
                 source="bulk_upload", added_at="2026-05-01T00:00:00Z",
                 meeting_ids=["m1"], draft_link="https://o/d1")
    _seed_crm(tmp_path, {"a@x.com": c})
    loaded = cs.load_crm(tmp_path)["contacts"]["a@x.com"]
    for f, v in c.items():
        assert loaded[f] == v, f"field {f} lost in migration: {loaded.get(f)!r} != {v!r}"
    assert cs.get_migration_status(tmp_path)["verdict"] == "lossless"


def test_migration_preserves_top_level_meta(tmp_path):
    _seed_crm(tmp_path, {"a@x.com": _contact()}, last_scan="2026-06-20T09:00:00Z", months=12)
    crm = cs.load_crm(tmp_path)
    assert crm["last_scan"] == "2026-06-20T09:00:00Z" and crm["months_scanned"] == 12


def test_migration_idempotent(tmp_path):
    _seed_crm(tmp_path, {"a@x.com": _contact(tags=["t1"])})
    cs.load_crm(tmp_path)                       # first access → import
    cs.update_contact_field(tmp_path, "a@x.com", "tags", ["t1", "t2"])
    cs.load_crm(tmp_path)                        # re-open must NOT re-import the stale file
    assert cs.load_crm(tmp_path)["contacts"]["a@x.com"]["tags"] == ["t1", "t2"]


# ── edit-preserving upsert (THE Daniel test) ─────────────────────────────────

def test_rebuild_preserves_user_cols(tmp_path):
    """An AI rebuild updates AI/derived columns but must NOT touch user columns."""
    _seed_crm(tmp_path, {"a@x.com": _contact(
        notes="[2026-06-01] important", tags=["investors"], priority="high",
        ignore=True, archived=False, manual=True, draft_link="https://o/d1")})
    cs.load_crm(tmp_path)
    built = {"a@x.com": _contact(company="NewCo", status="client", summary="fresh AI summary",
                                 thread_count=9, last_contact="2026-06-23")}
    cs.upsert_built_contacts(tmp_path, built)
    c = cs.load_crm(tmp_path)["contacts"]["a@x.com"]
    # AI + derived updated
    assert c["company"] == "NewCo" and c["status"] == "client" and c["summary"] == "fresh AI summary"
    assert c["thread_count"] == 9 and c["last_contact"] == "2026-06-23"
    # user columns preserved
    assert c["notes"] == "[2026-06-01] important"
    assert c["tags"] == ["investors"] and c["priority"] == "high"
    assert c["ignore"] is True and c["manual"] is True and c["draft_link"] == "https://o/d1"


def test_rebuild_is_race_safe_against_concurrent_edit(tmp_path):
    """The rebuild's `built` dict carries STALE user cols (it loaded minutes ago); a user edit
    happened since. The upsert must re-merge against the LIVE row → the concurrent edit survives."""
    _seed_crm(tmp_path, {"a@x.com": _contact(tags=["investors"], priority="medium")})
    cs.load_crm(tmp_path)
    # concurrent user edits land in the store AFTER the rebuild snapshotted
    cs.update_contact_field(tmp_path, "a@x.com", "tags", ["investors", "vip"])
    cs.update_contact_field(tmp_path, "a@x.com", "priority", "high")
    # rebuild finishes with STALE user cols + fresh AI cols
    built = {"a@x.com": _contact(company="NewCo", tags=["investors"], priority="medium")}
    cs.upsert_built_contacts(tmp_path, built)
    c = cs.load_crm(tmp_path)["contacts"]["a@x.com"]
    assert c["tags"] == ["investors", "vip"], "concurrent tag edit must NOT be clobbered by build"
    assert c["priority"] == "high", "concurrent priority edit must survive"
    assert c["company"] == "NewCo", "AI column still updates"


def test_empty_ai_value_falls_back_to_current(tmp_path):
    """A transient AI blank must not wipe a known-good AI field (reuses _merge_ai_enrichment rule)."""
    _seed_crm(tmp_path, {"a@x.com": _contact(company="GoodCo")})
    cs.load_crm(tmp_path)
    cs.upsert_built_contacts(tmp_path, {"a@x.com": _contact(company="")})  # AI returned blank
    assert cs.load_crm(tmp_path)["contacts"]["a@x.com"]["company"] == "GoodCo"


# ── readers / actions ────────────────────────────────────────────────────────

def test_get_ignored_emails(tmp_path):
    _seed_crm(tmp_path, {
        "a@x.com": _contact(email="a@x.com", ignore=True),
        "b@x.com": _contact(email="b@x.com", archived=True),
        "c@x.com": _contact(email="c@x.com")})
    assert cs.get_ignored_emails(tmp_path) == {"a@x.com", "b@x.com"}


def test_update_field_notes_appends(tmp_path):
    _seed_crm(tmp_path, {"a@x.com": _contact(notes="[2026-06-01] first")})
    cs.load_crm(tmp_path)
    cs.update_contact_field(tmp_path, "a@x.com", "notes", "second")
    notes = cs.load_crm(tmp_path)["contacts"]["a@x.com"]["notes"]
    assert "[2026-06-01] first" in notes and "second" in notes


def test_projection_keeps_crm_json_synced(tmp_path):
    _seed_crm(tmp_path, {"a@x.com": _contact()})
    cs.load_crm(tmp_path)
    cs.update_contact_field(tmp_path, "a@x.com", "priority", "high")
    proj = json.loads((tmp_path / "crm.json").read_text())
    assert proj["contacts"]["a@x.com"]["priority"] == "high"


def test_crm_py_wiring_round_trips_through_store(tmp_path):
    """The WIRED crm.py funcs (save_crm / update_contact / load_crm) round-trip through the store
    with the crm.json projection staying in sync — no store-vs-projection drift."""
    from src.modules import crm
    crm.save_crm(tmp_path, {"last_scan": "2026-06-23T00:00:00Z", "months_scanned": 6,
                            "contacts": {"a@x.com": _contact(tags=["vip"], priority="high", ignore=True)}})
    c = crm.load_crm(tmp_path)["contacts"]["a@x.com"]      # load reads the synced projection
    assert c["tags"] == ["vip"] and c["priority"] == "high" and c["ignore"] is True
    crm.update_contact(tmp_path, "a@x.com", "priority", "low")   # user edit → store
    assert crm.load_crm(tmp_path)["contacts"]["a@x.com"]["priority"] == "low"
    # store row and crm.json projection agree
    assert cs.load_crm(tmp_path)["contacts"]["a@x.com"]["priority"] == "low"
    proj = json.loads((tmp_path / "crm.json").read_text())["contacts"]["a@x.com"]
    assert proj["priority"] == "low" and proj["tags"] == ["vip"]


def test_delete_contact_removes_row_and_syncs_projection(tmp_path):
    _seed_crm(tmp_path, {"a@x.com": _contact(email="a@x.com"), "b@x.com": _contact(email="b@x.com")})
    cs.load_crm(tmp_path)
    assert cs.delete_contact(tmp_path, "B@X.com") is True       # case-insensitive
    out = cs.load_crm(tmp_path)["contacts"]
    assert "b@x.com" not in out and "a@x.com" in out
    proj = json.loads((tmp_path / "crm.json").read_text())["contacts"]
    assert "b@x.com" not in proj and "a@x.com" in proj          # projection synced
    assert cs.delete_contact(tmp_path, "nobody@x.com") is False


def test_migration_verdict_durable_and_readonly(tmp_path):
    assert cs.get_migration_status(tmp_path) == {"state": "not_accessed"}  # no DB yet, no trigger
    _seed_crm(tmp_path, {"a@x.com": _contact(tags=["t"])})
    cs.load_crm(tmp_path)
    st = cs.get_migration_status(tmp_path)
    assert st["state"] == "checked" and st["verdict"] == "lossless"
