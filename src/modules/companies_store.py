"""Companies store (Phase 3c of the single-store migration).

Brings the per-user companies database into the shared store.db. Companies is a DERIVED view —
identity / contacts / projects / derived_status / last_activity / thread_count are recomputed every
build from CRM + Projects (which are themselves in the store). Only a thin USER-STATE layer persists
across rebuilds: monitor_intelligence / ignore / notes / priority / name / manual / added_at, plus
manually-added companies. That user state is exactly what must live in the store (the derived half is
already there, via CRM/projects); companies.json becomes a synced read-only projection.

Mirrors crm_store/projects_store, with ONE difference: replace_from_dict does a FULL SYNC (upsert the
keys present, DELETE the keys absent) — because build_companies legitimately REMOVES derived companies
whose source CRM/Projects link disappeared. The dict passed to save is always the authoritative full
set (build re-applies user fields and keeps manual entries via companies._merge_company_user_fields),
so a full sync can't lose user data.
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
    con.execute("CREATE TABLE IF NOT EXISTS companies (key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS companies_meta (k TEXT PRIMARY KEY, v TEXT)")
    con.commit()
    _maybe_import(con, data_dir)
    return con


# ── one-time lazy migration from companies.json ──────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _maybe_import(con, data_dir) -> None:
    row = con.execute("SELECT v FROM companies_meta WHERE k='migrated_from_json'").fetchone()
    if row:
        if not con.execute("SELECT v FROM companies_meta WHERE k='migration_check'").fetchone():
            _verify_import(con, data_dir)   # backfill verdict for an already-migrated user
        return
    data_dir = Path(data_dir)
    db = _read_json(data_dir / "companies.json")
    companies = db.get("companies") or {}
    now = _now_iso()
    try:
        for key, rec in companies.items():
            if not key:
                continue
            con.execute("INSERT OR REPLACE INTO companies (key, data, updated_at) VALUES (?,?,?)",
                        (key, json.dumps(rec, ensure_ascii=False), now))
        con.execute("INSERT OR REPLACE INTO companies_meta (k, v) VALUES ('last_scan', ?)",
                    (json.dumps(db.get("last_scan")),))
    except Exception as e:
        print(f"[companies_store] import skipped/failed: {e}")
    con.execute("INSERT OR REPLACE INTO companies_meta (k, v) VALUES ('migrated_from_json', ?)", (now,))
    con.commit()
    _verify_import(con, data_dir)


def _verify_import(con, data_dir: Path) -> bool:
    """Lossless self-check: the store's company set must equal companies.json's, field-for-field.
    Writes a durable verdict to companies_meta + logs it. Best-effort."""
    try:
        db = _read_json(Path(data_dir) / "companies.json")
        json_companies = db.get("companies") or {}
        store_companies = {r["key"]: json.loads(r["data"]) for r in con.execute("SELECT key, data FROM companies")}
        missing = sorted(set(json_companies) - set(store_companies))
        field_loss = []
        for k in (set(json_companies) & set(store_companies)):
            jc, sc = json_companies[k], store_companies[k]
            for f, v in jc.items():
                if v not in (None, "", [], {}) and sc.get(f) != v:
                    field_loss.append(f"{k}.{f}")
        ok = not missing and not field_loss
        name = Path(data_dir).name
        payload = {"verdict": "lossless" if ok else "mismatch", "json": len(json_companies),
                   "store": len(store_companies), "lost": missing[:20],
                   "field_loss": field_loss[:20], "at": _now_iso()}
        con.execute("INSERT OR REPLACE INTO companies_meta (k, v) VALUES ('migration_check', ?)",
                    (json.dumps(payload),))
        con.commit()
        if ok:
            print(f"[companies_store] migration verified dir={name} companies={len(store_companies)} (lossless)")
        else:
            print(f"[companies_store] ⚠️ COMPANIES MIGRATION MISMATCH dir={name} json={len(json_companies)} "
                  f"store={len(store_companies)} lost={missing[:20]} field_loss={field_loss[:20]} "
                  f"— companies.json preserved; rollback possible")
        return ok
    except Exception as e:
        print(f"[companies_store] migration self-check skipped: {e}")
        return True


# ── write path ───────────────────────────────────────────────────────────────

def replace_from_dict(data_dir, db: dict) -> None:
    """The chokepoint behind companies.save_companies (build / update / add / delete all flow through
    it). FULL SYNC: upsert every company in the dict, then DELETE any store row whose key is no longer
    present — because build_companies removes derived companies whose source disappeared, and the dict
    is the authoritative full set (user fields already merged + manual entries kept upstream). Then
    regenerate the companies.json projection."""
    companies = (db or {}).get("companies") or {}
    keep_keys = set(companies)
    con = _conn(data_dir)
    try:
        now = _now_iso()
        for key, rec in companies.items():
            if not key:
                continue
            con.execute("INSERT OR REPLACE INTO companies (key, data, updated_at) VALUES (?,?,?)",
                        (key, json.dumps(rec, ensure_ascii=False), now))
        existing = {r["key"] for r in con.execute("SELECT key FROM companies")}
        for stale in (existing - keep_keys):
            con.execute("DELETE FROM companies WHERE key=?", (stale,))
        if "last_scan" in (db or {}):
            con.execute("INSERT OR REPLACE INTO companies_meta (k, v) VALUES ('last_scan', ?)",
                        (json.dumps(db.get("last_scan")),))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)


def clear(data_dir) -> None:
    """Drop all companies + meta (used by the onboarding reset endpoints). Best-effort."""
    path = _db_path(data_dir)
    if not path.exists():
        return
    con = open_sqlite(path)
    try:
        con.execute("DROP TABLE IF EXISTS companies")
        con.execute("DROP TABLE IF EXISTS companies_meta")
        con.commit()
    finally:
        con.close()


# ── read path ────────────────────────────────────────────────────────────────

def _meta(con, key, default=None):
    r = con.execute("SELECT v FROM companies_meta WHERE k=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return default


def load_companies(data_dir) -> dict:
    """Return the companies.json-shaped dict from the store (drop-in for companies.load_companies)."""
    con = _conn(data_dir)
    try:
        companies = {r["key"]: json.loads(r["data"]) for r in con.execute("SELECT key, data FROM companies")}
        return {"last_scan": _meta(con, "last_scan"), "companies": companies}
    finally:
        con.close()


def write_projection(data_dir) -> None:
    """Regenerate companies.json from the store so existing readers (company_intelligence section,
    server GET/export) keep working unchanged. Best-effort, atomic."""
    try:
        db = load_companies(data_dir)
        p = Path(data_dir) / "companies.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False))
        tmp.replace(p)
    except Exception as e:
        print(f"[companies_store] projection write failed: {e}")


def get_migration_status(data_dir) -> dict:
    """Read-only verdict for the admin endpoint — does NOT trigger migration."""
    path = _db_path(data_dir)
    if not path.exists():
        return {"state": "not_accessed"}
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        try:
            mig = con.execute("SELECT v FROM companies_meta WHERE k='migrated_from_json'").fetchone()
            chk = con.execute("SELECT v FROM companies_meta WHERE k='migration_check'").fetchone()
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
