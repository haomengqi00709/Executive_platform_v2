"""Companies store (Phase 3c). Companies is a derived view (recomputed from CRM/projects) plus a
user-state layer (monitor/ignore/notes/priority/name/manual) — the headline guards: lossless
migration, user state preserved, and the FULL-SYNC that drops a vanished derived company without
losing manual entries."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_comp_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import companies_store as cs   # noqa: E402


def _seed(d, companies, last_scan="2026-06-20T00:00:00Z"):
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / "companies.json").write_text(json.dumps({"last_scan": last_scan, "companies": companies}))


def _co(key="acme", **kw):
    base = {"key": key, "name": key.title(), "aliases": [key], "contacts": [], "contact_count": 0,
            "projects": [], "derived_status": "client", "last_activity": "2026-06-18",
            "thread_count_total": 3, "monitor_intelligence": True, "ignore": False,
            "notes": "", "priority": "medium", "manual": False, "added_at": None,
            "updated_at": "2026-06-18"}
    base.update(kw)
    return base


def test_migration_lossless_all_fields(tmp_path):
    c = _co("acme", notes="watch their funding", priority="high", monitor_intelligence=False,
            ignore=True, manual=True, added_at="2026-05-01T00:00:00Z")
    _seed(tmp_path, {"acme": c})
    loaded = cs.load_companies(tmp_path)["companies"]["acme"]
    for f, v in c.items():
        assert loaded[f] == v, f"field {f} lost: {loaded.get(f)!r} != {v!r}"
    assert cs.get_migration_status(tmp_path)["verdict"] == "lossless"


def test_migration_preserves_last_scan(tmp_path):
    _seed(tmp_path, {"acme": _co()}, last_scan="2026-06-20T09:00:00Z")
    assert cs.load_companies(tmp_path)["last_scan"] == "2026-06-20T09:00:00Z"


def test_user_fields_preserved_across_rebuild(tmp_path):
    """A rebuild re-applies user fields upstream (companies._merge_company_user_fields). The store
    must persist them: simulate a save that carries the merged user state."""
    _seed(tmp_path, {"acme": _co(notes="my note", priority="high", ignore=True, monitor_intelligence=False)})
    cs.load_companies(tmp_path)
    rebuilt = {"last_scan": "x", "companies": {"acme": _co(
        derived_status="prospect", thread_count_total=9,           # derived fields refreshed
        notes="my note", priority="high", ignore=True, monitor_intelligence=False)}}  # user fields carried
    cs.replace_from_dict(tmp_path, rebuilt)
    c = cs.load_companies(tmp_path)["companies"]["acme"]
    assert c["derived_status"] == "prospect" and c["thread_count_total"] == 9     # derived updated
    assert c["notes"] == "my note" and c["priority"] == "high"                    # user preserved
    assert c["ignore"] is True and c["monitor_intelligence"] is False


def test_full_sync_drops_vanished_derived_keeps_manual(tmp_path):
    """build removes a derived company whose source disappeared, but keeps manual entries. FULL-SYNC
    replace must delete the vanished one and retain the manual one."""
    _seed(tmp_path, {"acme": _co("acme"), "beta": _co("beta"),
                     "mine": _co("mine", manual=True, notes="hand-added")})
    cs.load_companies(tmp_path)
    # next build: 'beta' lost its CRM/project link → not in the dict; manual 'mine' kept
    cs.replace_from_dict(tmp_path, {"last_scan": "x", "companies": {
        "acme": _co("acme"), "mine": _co("mine", manual=True, notes="hand-added")}})
    out = cs.load_companies(tmp_path)["companies"]
    assert "beta" not in out                          # vanished derived dropped
    assert "acme" in out and out["mine"]["notes"] == "hand-added"   # manual survives, intact


def test_manual_company_survives_with_no_links(tmp_path):
    _seed(tmp_path, {})
    cs.replace_from_dict(tmp_path, {"companies": {"solo": _co("solo", manual=True, contacts=[], projects=[])}})
    assert cs.load_companies(tmp_path)["companies"]["solo"]["manual"] is True


def test_companies_py_wiring_round_trips(tmp_path):
    """The WIRED companies.py funcs (save_companies/load_companies + update/add/delete) round-trip
    through the store, projection synced."""
    from src.modules import companies
    companies.save_companies(tmp_path, {"last_scan": "x", "companies": {"acme": _co("acme")}})
    # add a manual company
    companies.add_manual_company(tmp_path, name="Nexus Capital", notes="investor", priority="high")
    keys = set(companies.load_companies(tmp_path)["companies"])
    assert "acme" in keys and "nexus capital" in keys
    # edit user field
    companies.update_company(tmp_path, "acme", {"priority": "high", "ignore": True})
    a = companies.load_companies(tmp_path)["companies"]["acme"]
    assert a["priority"] == "high" and a["ignore"] is True
    # store == projection
    assert cs.load_companies(tmp_path)["companies"]["acme"]["priority"] == "high"
    proj = json.loads((tmp_path / "companies.json").read_text())["companies"]["acme"]
    assert proj["ignore"] is True
    # delete
    assert companies.delete_company(tmp_path, "acme") is True
    assert "acme" not in companies.load_companies(tmp_path)["companies"]
    assert "acme" not in cs.load_companies(tmp_path)["companies"]    # store synced on delete


def test_projection_synced(tmp_path):
    _seed(tmp_path, {"acme": _co()})
    cs.load_companies(tmp_path)
    cs.replace_from_dict(tmp_path, {"companies": {"acme": _co(priority="high")}})
    assert json.loads((tmp_path / "companies.json").read_text())["companies"]["acme"]["priority"] == "high"


def test_verdict_durable_and_readonly(tmp_path):
    assert cs.get_migration_status(tmp_path) == {"state": "not_accessed"}
    _seed(tmp_path, {"acme": _co()})
    cs.load_companies(tmp_path)
    st = cs.get_migration_status(tmp_path)
    assert st["state"] == "checked" and st["verdict"] == "lossless"
