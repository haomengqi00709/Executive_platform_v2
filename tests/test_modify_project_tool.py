"""F2 (modify_project): the bot can change a project through the store — field-level (sibling
user columns preserved), with reference resolution (#N / id / name) and validation."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_modproj_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects_store as ps                                # noqa: E402
from src.bot_tools.projects.modify_project.tool import build                # noqa: E402


def _ctx(tmp_path, state=None):
    return SimpleNamespace(data_dir=tmp_path, settings={"timezone": "UTC"}, state=state or {})


def _proj(pid, status="ongoing", **kw):
    base = {"id": pid, "name": pid.replace("-", " ").title(), "status": status, "momentum": "steady",
            "category": "deal", "ignore": False, "tags": ["keep"], "conversation_ids": ["c1"],
            "last_activity": "2026-06-20"}
    base.update(kw)
    return base


def _seed(tmp_path, projects):
    ps.replace_from_dict(tmp_path, {"last_scan": "x", "projects": projects})


def test_set_status_through_store_preserves_siblings(tmp_path):
    _seed(tmp_path, {"nexus-deal": _proj("nexus-deal")})
    out = build(_ctx(tmp_path))("nexus", "status", "paused")
    assert "✅" in out
    p = ps.load_projects(tmp_path)["projects"]["nexus-deal"]
    assert p["status"] == "paused"                                  # changed
    assert p["tags"] == ["keep"] and p["conversation_ids"] == ["c1"]  # siblings preserved
    # projection synced
    assert json.loads((tmp_path / "projects.json").read_text())["projects"]["nexus-deal"]["status"] == "paused"


def test_ignore_and_unignore(tmp_path):
    _seed(tmp_path, {"x-proj": _proj("x-proj")})
    build(_ctx(tmp_path))("x-proj", "ignore", "true")
    assert ps.load_projects(tmp_path)["projects"]["x-proj"]["ignore"] is True
    # un-ignore must still resolve (id/name search spans ignored projects)
    build(_ctx(tmp_path))("x-proj", "ignore", "false")
    assert ps.load_projects(tmp_path)["projects"]["x-proj"]["ignore"] is False


def test_resolve_by_shown_position(tmp_path):
    _seed(tmp_path, {"a": _proj("a"), "b": _proj("b")})
    state = {"_shown_lists": {"projects": {"items": [
        {"pos": 1, "id": "a", "label": "A"}, {"pos": 2, "id": "b", "label": "B"}]}}}
    out = build(_ctx(tmp_path, state))("2", "status", "completed")   # "the 2nd one I saw" → b
    assert "✅" in out
    assert ps.load_projects(tmp_path)["projects"]["b"]["status"] == "completed"
    assert ps.load_projects(tmp_path)["projects"]["a"]["status"] == "ongoing"


def test_invalid_status_rejected_no_change(tmp_path):
    _seed(tmp_path, {"a": _proj("a", status="ongoing")})
    out = build(_ctx(tmp_path))("a", "status", "bogus")
    assert "Invalid status" in out
    assert ps.load_projects(tmp_path)["projects"]["a"]["status"] == "ongoing"   # unchanged


def test_non_editable_field_rejected(tmp_path):
    _seed(tmp_path, {"a": _proj("a")})
    out = build(_ctx(tmp_path))("a", "thread_count", "99")
    assert "Can't set" in out


def test_no_match_is_honest(tmp_path):
    _seed(tmp_path, {"a": _proj("a")})
    out = build(_ctx(tmp_path))("nonexistent-project", "status", "paused")
    assert "can't match" in out.lower()


def test_compressed_name_resolves_by_token_subset(tmp_path):
    """The model passes a COMPRESSED name not contiguous in the full name. Token-subset must match."""
    _seed(tmp_path, {"ips-consultancy-cto-role-alignment":
                     _proj("ips-consultancy-cto-role-alignment", name="IPS Consultancy — CTO Role Alignment")})
    out = build(_ctx(tmp_path))("IPS CTO Role Alignment", "status", "ongoing")   # not a substring
    assert "✅" in out
    assert _proj_status(tmp_path, "ips-consultancy-cto-role-alignment") == "ongoing"


def _proj_status(tmp_path, pid):
    from src.modules import projects_store
    return projects_store.load_projects(tmp_path)["projects"][pid].get("status")


def test_token_subset_ambiguous_does_not_guess(tmp_path):
    """Two projects whose names BOTH contain the hint words non-contiguously → token-subset path
    sees two matches → don't guess (names chosen so the hint isn't a contiguous substring of either)."""
    _seed(tmp_path, {"a": _proj("a", name="Strategy work for Acme on AI"),
                     "b": _proj("b", name="Strategy work for Beta on AI")})
    out = build(_ctx(tmp_path))("AI Strategy", "status", "paused")   # not contiguous in either
    assert "can't match" in out.lower()        # ambiguous → honest, no wrong write
