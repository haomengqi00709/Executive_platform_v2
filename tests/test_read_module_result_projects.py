"""F1 (read alignment): the bot's read_module_result for projects reads the LIVE store, not the
stale results/project_status.json render cache. Headline test: a bogus cache is ignored — the bot
returns what's in the store. Mirrors the commitments live-read guarantee."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_rmr_proj_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects_store as ps                       # noqa: E402
from src.bot_tools.sections.read_module_result.tool import build   # noqa: E402


def _ctx(tmp_path):
    return SimpleNamespace(data_dir=tmp_path, settings={"timezone": "UTC"}, state={})


def _proj(pid, status, **kw):
    base = {"id": pid, "name": pid.replace("-", " ").title(), "status": status, "momentum": "steady",
            "category": "deal", "summary": f"{pid} summary", "next_action": "do X",
            "last_activity": "2026-06-20", "ignore": False, "thread_count": 1}
    base.update(kw)
    return base


def _read(tmp_path, section):
    return json.loads(build(_ctx(tmp_path))(section))


def test_project_status_reads_live_store(tmp_path):
    ps.replace_from_dict(tmp_path, {"last_scan": "x", "projects": {
        "acme": _proj("acme", "ongoing"), "beta": _proj("beta", "paused")}})
    data = _read(tmp_path, "project_status")
    assert data["status"] == "fresh"
    assert {it["id"] for it in data["items"]} == {"acme", "beta"}
    assert all("index" in it for it in data["items"])               # [#N] addressing applied


def test_ignores_stale_results_cache(tmp_path):
    """THE fix: a stale results/project_status.json must NOT be served — the store wins."""
    ps.replace_from_dict(tmp_path, {"projects": {"real": _proj("real", "ongoing")}})
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "project_status.json").write_text(json.dumps({
        "id": "project_status", "status": "fresh", "last_run": "2026-06-23T00:00:00Z",
        "items": [{"id": "ghost-old-id", "name": "Ghost", "status": "ongoing"}], "count": 1}))
    data = _read(tmp_path, "project_status")
    ids = {it["id"] for it in data["items"]}
    assert ids == {"real"} and "ghost-old-id" not in ids


def test_edit_reflects_immediately(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {"acme": _proj("acme", "ongoing")}})
    assert _read(tmp_path, "project_status")["items"][0]["status"] == "ongoing"
    ps.update_project_fields(tmp_path, "acme", {"status": "paused"})
    assert _read(tmp_path, "project_status")["items"][0]["status"] == "paused"   # live, no re-run
    ps.update_project_fields(tmp_path, "acme", {"ignore": True})
    assert _read(tmp_path, "project_status")["items"] == []                       # ignored drops off


def test_status_filter_excludes_completed_and_ignored(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {
        "a": _proj("a", "ongoing"), "done": _proj("done", "completed"),
        "ign": _proj("ign", "ongoing", ignore=True), "arc": _proj("arc", "ongoing", archived=True)}})
    ids = {it["id"] for it in _read(tmp_path, "project_status")["items"]}
    assert ids == {"a"}                                              # completed/ignore/archived all out


def test_projects_needing_attention_filter(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {
        "na": _proj("na", "needs_attention"), "es": _proj("es", "early_stage"),
        "on": _proj("on", "ongoing"), "pa": _proj("pa", "paused")}})
    ids = {it["id"] for it in _read(tmp_path, "projects_needing_attention")["items"]}
    assert ids == {"na", "es"}                                       # only needs_attention/early_stage
