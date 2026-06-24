"""Unit tests for the Projects SQLite store (Phase 3b). The headline tests guard Daniel's
customizations: lossless migration + field-level PATCH that never clobbers sibling user columns,
and the reset-clear that stops stale rows surviving a from-scratch rebuild."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_proj_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects_store as ps  # noqa: E402


def _seed(d, projects, last_scan="2026-06-20T00:00:00Z"):
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / "projects.json").write_text(json.dumps({"last_scan": last_scan, "projects": projects}))


def _proj(pid="acme-deal", **kw):
    base = {"id": pid, "name": "Acme Deal", "summary": "ongoing negotiation", "status": "ongoing",
            "momentum": "steady", "category": "deal", "next_action": "send proposal",
            "participants": ["bob@acme.com"], "conversation_ids": ["c1", "c2"], "key_topics": ["pricing"],
            "thread_count": 2, "last_activity": "2026-06-18", "ignore": False, "updated_at": "2026-06-18"}
    base.update(kw)
    return base


# ── lazy migration is lossless ───────────────────────────────────────────────

def test_migration_lossless_all_fields(tmp_path):
    p = _proj(ignore=True, deadline="2026-07-01", archived=False, source="bulk_upload",
              meeting_ids=["m1"], dormant=False)
    _seed(tmp_path, {"acme-deal": p})
    loaded = ps.load_projects(tmp_path)["projects"]["acme-deal"]
    for f, v in p.items():
        assert loaded[f] == v, f"field {f} lost in migration: {loaded.get(f)!r} != {v!r}"
    assert ps.get_migration_status(tmp_path)["verdict"] == "lossless"


def test_migration_preserves_last_scan(tmp_path):
    _seed(tmp_path, {"acme-deal": _proj()}, last_scan="2026-06-20T09:00:00Z")
    assert ps.load_projects(tmp_path)["last_scan"] == "2026-06-20T09:00:00Z"


def test_migration_idempotent(tmp_path):
    _seed(tmp_path, {"acme-deal": _proj(status="ongoing")})
    ps.load_projects(tmp_path)                                     # first access → import
    ps.update_project_fields(tmp_path, "acme-deal", {"status": "paused"})
    ps.load_projects(tmp_path)                                     # re-open must NOT re-import stale file
    assert ps.load_projects(tmp_path)["projects"]["acme-deal"]["status"] == "paused"


# ── field-level PATCH never clobbers sibling user columns (THE Daniel test) ───

def test_patch_field_level_preserves_user_cols(tmp_path):
    """The user set ignore + category + deadline. A later PATCH that only changes status must NOT
    wipe those — update_project_fields edits only the given fields on the live row."""
    _seed(tmp_path, {"acme-deal": _proj(ignore=True, category="strategic", deadline="2026-07-01")})
    ps.load_projects(tmp_path)
    ps.update_project_fields(tmp_path, "acme-deal", {"status": "needs_attention"})
    p = ps.load_projects(tmp_path)["projects"]["acme-deal"]
    assert p["status"] == "needs_attention"                       # the edit applied
    assert p["ignore"] is True and p["category"] == "strategic" and p["deadline"] == "2026-07-01"


def test_patch_unioned_fields_preserved(tmp_path):
    """A PATCH must not drop the accumulate columns (participants/conversation_ids/key_topics)."""
    _seed(tmp_path, {"acme-deal": _proj()})
    ps.load_projects(tmp_path)
    ps.update_project_fields(tmp_path, "acme-deal", {"name": "Acme Deal (renamed)"})
    p = ps.load_projects(tmp_path)["projects"]["acme-deal"]
    assert p["conversation_ids"] == ["c1", "c2"] and p["participants"] == ["bob@acme.com"]


def test_update_nonexistent_returns_none(tmp_path):
    _seed(tmp_path, {"acme-deal": _proj()})
    ps.load_projects(tmp_path)
    assert ps.update_project_fields(tmp_path, "does-not-exist", {"status": "paused"}) is None


# ── whole-dict save path (build/refresh/bulk-commit chokepoint) ──────────────

def test_replace_from_dict_round_trips_lossless(tmp_path):
    _seed(tmp_path, {"acme-deal": _proj(ignore=True)})
    ps.load_projects(tmp_path)
    db = ps.load_projects(tmp_path)
    db["projects"]["acme-deal"]["status"] = "completed"           # simulate a refresh result
    db["projects"]["new-proj"] = _proj("new-proj", name="New", ignore=False)
    db["last_scan"] = "2026-06-24T00:00:00Z"
    ps.replace_from_dict(tmp_path, db)
    out = ps.load_projects(tmp_path)
    assert out["projects"]["acme-deal"]["status"] == "completed"
    assert out["projects"]["acme-deal"]["ignore"] is True         # user col carried through
    assert out["projects"]["new-proj"]["name"] == "New"
    assert out["last_scan"] == "2026-06-24T00:00:00Z"


def test_replace_from_dict_is_upsert_only_no_delete(tmp_path):
    """A caller passing a SHRUNK dict must not delete existing rows (refresh never shrinks; this
    guards against a buggy partial-dict caller silently dropping projects)."""
    _seed(tmp_path, {"acme-deal": _proj(), "beta-proj": _proj("beta-proj", name="Beta")})
    ps.load_projects(tmp_path)
    ps.replace_from_dict(tmp_path, {"projects": {"acme-deal": _proj(status="paused")}})
    out = ps.load_projects(tmp_path)["projects"]
    assert "beta-proj" in out and out["acme-deal"]["status"] == "paused"


# ── projection / wiring / verdict / reset ────────────────────────────────────

def test_projection_keeps_projects_json_synced(tmp_path):
    _seed(tmp_path, {"acme-deal": _proj()})
    ps.load_projects(tmp_path)
    ps.update_project_fields(tmp_path, "acme-deal", {"status": "paused"})
    proj = json.loads((tmp_path / "projects.json").read_text())
    assert proj["projects"]["acme-deal"]["status"] == "paused"


def test_projects_py_wiring_round_trips_through_store(tmp_path):
    """The WIRED projects.py funcs (save_projects / load_projects) round-trip through the store with
    the projects.json projection staying in sync — no store-vs-projection drift."""
    from src.modules import projects
    projects.save_projects(tmp_path, {"last_scan": "2026-06-24T00:00:00Z",
                                       "projects": {"acme-deal": _proj(ignore=True, category="deal")}})
    p = projects.load_projects(tmp_path)["projects"]["acme-deal"]   # reads the synced projection
    assert p["ignore"] is True and p["category"] == "deal"
    # store row and projects.json projection agree
    assert ps.load_projects(tmp_path)["projects"]["acme-deal"]["ignore"] is True
    proj = json.loads((tmp_path / "projects.json").read_text())["projects"]["acme-deal"]
    assert proj["category"] == "deal"


def test_migration_verdict_durable_and_readonly(tmp_path):
    assert ps.get_migration_status(tmp_path) == {"state": "not_accessed"}   # no DB yet, no trigger
    _seed(tmp_path, {"acme-deal": _proj()})
    ps.load_projects(tmp_path)
    st = ps.get_migration_status(tmp_path)
    assert st["state"] == "checked" and st["verdict"] == "lossless"


def test_delete_project_removes_row_and_syncs_projection(tmp_path):
    _seed(tmp_path, {"a": _proj("a", name="A"), "b": _proj("b", name="B")})
    ps.load_projects(tmp_path)
    assert ps.delete_project(tmp_path, "b") is True
    out = ps.load_projects(tmp_path)["projects"]
    assert "b" not in out and "a" in out
    proj = json.loads((tmp_path / "projects.json").read_text())["projects"]
    assert "b" not in proj and "a" in proj                     # projection synced
    assert ps.delete_project(tmp_path, "nope") is False        # no-op on missing


def test_clear_resets_store_no_stale_rows(tmp_path):
    """Reset deletes projects.json + clears the store. A from-scratch rebuild then must NOT inherit
    pre-reset rows (the upsert-only replace_from_dict can't delete them itself)."""
    _seed(tmp_path, {"old-proj": _proj("old-proj", name="Old")})
    ps.load_projects(tmp_path)
    (tmp_path / "projects.json").unlink()       # reset deletes the JSON
    ps.clear(tmp_path)                          # …and clears the store
    ps.replace_from_dict(tmp_path, {"last_scan": "x", "projects": {"fresh-proj": _proj("fresh-proj")}})
    out = ps.load_projects(tmp_path)["projects"]
    assert "old-proj" not in out and "fresh-proj" in out
