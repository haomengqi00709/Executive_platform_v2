"""Projects store (Phase 3b of the single-store migration).

Brings the per-user project database into the shared store.db (same file as commitments/email/crm,
separate tables). Mirrors crm_store.py exactly: each project is its own row keyed by its stable
kebab-case id (projects.py generates ids that survive rebuilds), stored as a JSON blob — so EVERY
field (AI / user / accumulate) is preserved verbatim and all the existing merge/preserve logic in
projects.py stays untouched (we only swap persistence).

DATA-LOSS PREVENTION (Daniel has heavy customization — must not lose it):
  1. One-time lazy import is LOSSLESS — every field of every project carried over verbatim,
     projects.json kept as a synced projection + backup, reversible.
  2. The build/refresh write path (replace_from_dict) is exact parity with the prior whole-file
     save_projects: edit-preservation already happens UPSTREAM in projects.refresh_projects /
     _merge_projects (only AI cols written when non-empty, `ignore` preserved, conversation_ids
     unioned). The server PATCH is now a field-level store update — it never rewrites the whole
     object, so it cannot clobber sibling user columns.

last_scan lives in projects_meta. Readers keep reading the projects.json projection
(write_projection keeps it synced) — no reader change required.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.modules.db_helpers import open_sqlite


def _db_path(data_dir) -> Path:
    return Path(data_dir) / "store.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(data_dir):
    path = _db_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_sqlite(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS projects_meta (k TEXT PRIMARY KEY, v TEXT)")
    con.commit()
    _maybe_import(con, data_dir)
    return con


# ── one-time lazy migration from projects.json ───────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _maybe_import(con, data_dir) -> None:
    row = con.execute("SELECT v FROM projects_meta WHERE k='migrated_from_json'").fetchone()
    if row:
        if not con.execute("SELECT v FROM projects_meta WHERE k='migration_check'").fetchone():
            _verify_import(con, data_dir)   # backfill verdict for an already-migrated user
        return
    data_dir = Path(data_dir)
    db = _read_json(data_dir / "projects.json")
    projects = db.get("projects") or {}
    now = _now_iso()
    try:
        for pid, proj in projects.items():
            if not pid:
                continue
            con.execute("INSERT OR REPLACE INTO projects (id, data, updated_at) VALUES (?,?,?)",
                        (pid, json.dumps(proj, ensure_ascii=False), now))
        con.execute("INSERT OR REPLACE INTO projects_meta (k, v) VALUES ('last_scan', ?)",
                    (json.dumps(db.get("last_scan")),))
    except Exception as e:
        print(f"[projects_store] import skipped/failed: {e}")
    con.execute("INSERT OR REPLACE INTO projects_meta (k, v) VALUES ('migrated_from_json', ?)", (now,))
    con.commit()
    _verify_import(con, data_dir)


def _verify_import(con, data_dir: Path) -> bool:
    """Lossless self-check: the store's project set must equal projects.json's, field-for-field.
    Writes a durable verdict to projects_meta (logs can be dropped under load) + logs it. Best-effort."""
    try:
        db = _read_json(Path(data_dir) / "projects.json")
        json_projects = db.get("projects") or {}
        store_projects = {r["id"]: json.loads(r["data"]) for r in con.execute("SELECT id, data FROM projects")}
        missing = sorted(set(json_projects) - set(store_projects))   # in JSON, lost in store
        field_loss = []
        for pid in (set(json_projects) & set(store_projects)):
            jp, sp = json_projects[pid], store_projects[pid]
            for f, v in jp.items():
                if v not in (None, "", [], {}) and sp.get(f) != v:
                    field_loss.append(f"{pid}.{f}")
        ok = not missing and not field_loss
        name = Path(data_dir).name
        payload = {"verdict": "lossless" if ok else "mismatch", "json": len(json_projects),
                   "store": len(store_projects), "lost": missing[:20],
                   "field_loss": field_loss[:20], "at": _now_iso()}
        con.execute("INSERT OR REPLACE INTO projects_meta (k, v) VALUES ('migration_check', ?)",
                    (json.dumps(payload),))
        con.commit()
        if ok:
            print(f"[projects_store] migration verified dir={name} projects={len(store_projects)} (lossless)")
        else:
            print(f"[projects_store] ⚠️ PROJECTS MIGRATION MISMATCH dir={name} json={len(json_projects)} "
                  f"store={len(store_projects)} lost={missing[:20]} field_loss={field_loss[:20]} "
                  f"— projects.json preserved; rollback possible")
        return ok
    except Exception as e:
        print(f"[projects_store] migration self-check skipped: {e}")
        return True


# ── write paths ──────────────────────────────────────────────────────────────

def replace_from_dict(data_dir, db: dict) -> None:
    """Whole-dict save path (the chokepoint behind projects.save_projects — used by build/refresh/
    bulk-commit). Upserts every project as a full row + sets last_scan meta, then regenerates the
    projects.json projection. UPSERT-ONLY (never deletes a row) — projects are not hard-deleted by
    the rebuild (refresh re-assesses in place; bulk-commit only adds), so never-deleting is the safe
    default. Edit-preservation for the AI rebuild is handled UPSTREAM in projects.refresh_projects /
    _merge_projects (parity with the prior whole-file projects.json behaviour)."""
    projects = (db or {}).get("projects") or {}
    con = _conn(data_dir)
    try:
        now = _now_iso()
        for pid, proj in projects.items():
            if not pid:
                continue
            con.execute("INSERT OR REPLACE INTO projects (id, data, updated_at) VALUES (?,?,?)",
                        (pid, json.dumps(proj, ensure_ascii=False), now))
        if "last_scan" in (db or {}):
            con.execute("INSERT OR REPLACE INTO projects_meta (k, v) VALUES ('last_scan', ?)",
                        (json.dumps(db.get("last_scan")),))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)


def update_project_fields(data_dir, project_id: str, updates: dict, updated_at: str = None) -> dict | None:
    """Field-level user edit (the server PATCH chokepoint). Reads the project's blob, applies ONLY
    the given fields, stamps updated_at, writes the row back atomically — sibling user columns are
    never touched. Returns the updated project, or None if the project does not exist (caller raises
    404). The editable-field whitelist + status/momentum validation stay in the server endpoint."""
    con = _conn(data_dir)
    try:
        r = con.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        if not r:
            return None
        proj = json.loads(r["data"])
        proj.update(updates or {})
        proj["updated_at"] = updated_at or datetime.now().strftime("%Y-%m-%d")
        proj.setdefault("id", project_id)
        con.execute("INSERT OR REPLACE INTO projects (id, data, updated_at) VALUES (?,?,?)",
                    (project_id, json.dumps(proj, ensure_ascii=False), _now_iso()))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)
    return proj


def delete_project(data_dir, project_id: str) -> bool:
    """Remove a single project row (used by db_cleaner's merge — the duplicate is deleted; replace_from_dict
    is upsert-only and can't propagate a deletion). Regenerates the projection so readers see it gone
    immediately. Returns True if a row was removed."""
    con = _conn(data_dir)
    try:
        cur = con.execute("DELETE FROM projects WHERE id=?", (project_id,))
        con.commit()
        removed = cur.rowcount > 0
    finally:
        con.close()
    write_projection(data_dir)
    return removed


def clear(data_dir) -> None:
    """Drop all projects + meta (used by the onboarding reset/cleanup endpoints, which delete
    projects.json to rebuild from scratch). Without this, the upsert-only replace_from_dict would
    leave pre-reset rows behind. The next store access re-imports from the (now empty/absent) JSON."""
    path = _db_path(data_dir)
    if not path.exists():
        return
    con = open_sqlite(path)
    try:
        con.execute("DROP TABLE IF EXISTS projects")
        con.execute("DROP TABLE IF EXISTS projects_meta")
        con.commit()
    finally:
        con.close()


# ── read path ────────────────────────────────────────────────────────────────

def _meta(con, key, default=None):
    r = con.execute("SELECT v FROM projects_meta WHERE k=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return default


def load_projects(data_dir) -> dict:
    """Return the projects.json-shaped dict from the store (drop-in for projects.load_projects)."""
    con = _conn(data_dir)
    try:
        projects = {r["id"]: json.loads(r["data"]) for r in con.execute("SELECT id, data FROM projects")}
        return {"last_scan": _meta(con, "last_scan"), "projects": projects}
    finally:
        con.close()


# Display ordering for the live list — most-attention-worthy first (mirrors project_status.run).
_STATUS_RANK = {"needs_attention": 0, "ongoing": 1, "paused": 2, "early_stage": 3, "completed": 4}


def query_live_projects(data_dir, statuses=None, ignore_archived=True) -> list[dict]:
    """Live project list for the bot's interactive read (the read-side mirror of
    commitments_store.query_visible). Applies the SAME deterministic filter project_status.run uses
    — drop ignore/archived, keep the given status set — but WITHOUT the AI validator, so the bot's
    'what projects do I have' is fresh + free + never a stale render cache. Sorted attention-first
    then most-recent (same idiom as the section). Returns the full project dicts; the caller shapes
    for display. `statuses=None` means no status filter."""
    out = []
    for p in (load_projects(data_dir).get("projects") or {}).values():
        if ignore_archived and (p.get("ignore") or p.get("archived")):
            continue
        if statuses is not None and p.get("status") not in statuses:
            continue
        out.append(p)
    out.sort(key=lambda p: p.get("last_activity") or "", reverse=True)   # recency within a rank
    out.sort(key=lambda p: _STATUS_RANK.get(p.get("status", ""), 9))     # stable → attention first
    return out


def write_projection(data_dir) -> None:
    """Regenerate projects.json from the store so every existing reader (project_status,
    projects_needing_attention, business_insights, meeting_prep, reply/followup_needed) keeps
    working unchanged. Best-effort, atomic."""
    try:
        db = load_projects(data_dir)
        p = Path(data_dir) / "projects.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False))
        tmp.replace(p)
    except Exception as e:
        print(f"[projects_store] projection write failed: {e}")


def get_migration_status(data_dir) -> dict:
    """Read-only verdict for the admin endpoint — does NOT trigger migration."""
    path = _db_path(data_dir)
    if not path.exists():
        return {"state": "not_accessed"}
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        try:
            mig = con.execute("SELECT v FROM projects_meta WHERE k='migrated_from_json'").fetchone()
            chk = con.execute("SELECT v FROM projects_meta WHERE k='migration_check'").fetchone()
        except Exception as e:
            return {"state": "error", "error": str(e)}
    finally:
        con.close()
    if not mig:
        return {"state": "no_flag"}
    if not chk:
        return {"state": "migrated_unchecked"}
    try:
        return {"state": "checked", **json.loads(chk["v"])}
    except Exception:
        return {"state": "checked", "raw": chk["v"]}
