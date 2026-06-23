"""
commitments_store — single live SQLite source of truth for per-user commitments.

Replaces the three drifting JSON files:
  - commitments_extract.json  (cached snapshot of items)   → `commitments` table rows
  - commitments_state.json    (done/asked/snoozed status)  → status columns ON the same row
  - commitments_cache.json    (incremental dedup + raw AI)  → `processed_emails` table

Reads are QUERIES against the store, so a just-marked/skipped/snoozed item is reflected
immediately (no snapshot-vs-state drift). Status lives INLINE on the commitment row — there
is intentionally no separate status table (that would re-create the split we're removing).

The legacy JSON files are kept as a read-only PROJECTION (for the dashboard via
/api/sections/* and for yesterday_recap) — see write_projection(). On a user's first access
the existing JSON is imported once (lazy, idempotent, reversible: delete store.db to redo).

All connections go through db_helpers.open_sqlite (WAL + busy_timeout, SMB-safe).
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.modules.db_helpers import open_sqlite
from src.modules.tz import get_user_tz, today_local_str

_DB_NAME = "store.db"

# Item content columns (everything EXCEPT status/* — those are never touched by upsert).
_CONTENT_COLS = [
    "type", "description", "due_date", "due_date_confidence", "contact_email",
    "contact_name", "email_id", "subject", "received", "priority",
    "contact_json", "project_json",
]


def _db_path(data_dir) -> Path:
    return Path(data_dir) / _DB_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(data_dir):
    """Open the store, creating tables + running the one-time JSON import if needed."""
    path = _db_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_sqlite(path)
    con.row_factory = __import__("sqlite3").Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS commitments (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            due_date TEXT,
            due_date_confidence TEXT,
            contact_email TEXT,
            contact_name TEXT,
            email_id TEXT,
            subject TEXT,
            received TEXT,
            priority TEXT DEFAULT 'medium',
            contact_json TEXT,
            project_json TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            status_at TEXT,
            status_method TEXT,
            snoozed_until TEXT,
            asked_expires_at TEXT,
            asked_at TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS ix_c_status ON commitments(status)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_c_due ON commitments(due_date)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_c_email ON commitments(email_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_c_type_due ON commitments(type, due_date)")
    con.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            email_id TEXT PRIMARY KEY,
            received TEXT,
            extracted_at TEXT,
            raw_extraction_json TEXT,
            msg_meta_json TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS ix_pe_received ON processed_emails(received)")
    con.execute("CREATE TABLE IF NOT EXISTS store_meta (k TEXT PRIMARY KEY, v TEXT)")
    con.commit()
    _maybe_import(con, data_dir)
    return con


# ── one-time lazy migration from the legacy JSON files ──────────────────────

def _maybe_import(con, data_dir) -> None:
    row = con.execute("SELECT v FROM store_meta WHERE k='migrated_from_json'").fetchone()
    if row:
        # Already migrated. Backfill the durable verdict if it predates this feature, so a user
        # who migrated BEFORE the verdict was persisted (e.g. a client) still gets a queryable
        # result on their next access — verification can't depend on a log line that may be dropped.
        chk = con.execute("SELECT v FROM store_meta WHERE k='migration_check'").fetchone()
        if not chk:
            _verify_import(con, Path(data_dir))
        return
    data_dir = Path(data_dir)
    try:
        _import_from_json(con, data_dir)
    except Exception as e:
        print(f"[commitments_store] import skipped/failed: {e}")
    con.execute("INSERT OR REPLACE INTO store_meta (k, v) VALUES ('migrated_from_json', ?)",
                (_now_iso(),))
    con.commit()
    # Self-verify the one-time migration: the store's visible set MUST equal the legacy JSON read
    # path on the same data. A mismatch (loss / resurrection) is logged LOUDLY so it surfaces the
    # moment ANY user — including clients whose data we could not pre-verify — first migrates.
    _verify_import(con, data_dir)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _import_from_json(con, data_dir: Path) -> None:
    extract = _read_json(data_dir / "results" / "commitments_extract.json")
    state = _read_json(data_dir / "commitments_state.json")
    cache = _read_json(data_dir / "commitments_cache.json")
    now = _now_iso()

    # 1. items
    for it in extract.get("items", []) or []:
        if not it.get("id"):
            continue
        _insert_content(con, it, now)
    # 2. status overlay
    for cid, info in (state.get("done") or {}).items():
        _ensure_row(con, cid, now)
        con.execute("UPDATE commitments SET status='done', status_at=?, status_method=?, "
                    "asked_expires_at=NULL, snoozed_until=NULL WHERE id=?",
                    (info.get("at") or now, info.get("method") or "user", cid))
    # snoozed/asked apply ONLY to commitments still in the snapshot. A snoozed/asked id no
    # longer in the extract is a gone commitment — do NOT _ensure_row it (a blank placeholder
    # would surface as an empty commitment once the snooze expires). Only 'done' gets a
    # placeholder, so a re-extraction can't resurrect a resolved item.
    for cid, info in (state.get("snoozed") or {}).items():
        con.execute("UPDATE commitments SET status='snoozed', snoozed_until=?, "
                    "asked_expires_at=NULL WHERE id=? AND status!='done'",
                    (info.get("until"), cid))
    for cid, info in (state.get("asked") or {}).items():
        con.execute("UPDATE commitments SET asked_at=?, asked_expires_at=? "
                    "WHERE id=? AND status='open'",
                    (info.get("asked_at"), info.get("expires_at"), cid))
    # 3. processed-email cache
    for eid, entry in (cache.get("emails") or {}).items():
        con.execute(
            "INSERT OR REPLACE INTO processed_emails "
            "(email_id, received, extracted_at, raw_extraction_json, msg_meta_json) "
            "VALUES (?,?,?,?,?)",
            (eid, entry.get("received"), entry.get("extracted_at"),
             json.dumps(entry.get("commitments") or []),
             json.dumps(entry.get("msg_meta") or {})))
    con.commit()


def _verify_import(con, data_dir: Path) -> bool:
    """One-time migration self-check: compare the store's visible set to the legacy read path
    (commitments_extract.json filtered by commitments_state.should_show) on the SAME data. They
    must be identical — that's what 'lossless' means. Returns True on match; logs a loud, greppable
    'MIGRATION MISMATCH' on divergence. Uses the live `con` (no re-entrant _conn). Best-effort:
    never raises into the import path."""
    try:
        from src.modules.commitments_state import load_state, should_show
        today = today_local_str(data_dir)
        extract = _read_json(Path(data_dir) / "results" / "commitments_extract.json")
        st = load_state(Path(data_dir))
        old_ids = {it["id"] for it in (extract.get("items") or [])
                   if it.get("id") and should_show(it["id"], st, today)}
        where, params = _visible_clause(today)
        new_ids = {r["id"] for r in con.execute(
            f"SELECT id FROM commitments WHERE {where}", params).fetchall()}
        name = Path(data_dir).name
        ok = old_ids == new_ids
        payload = {
            "verdict":     "lossless" if ok else "mismatch",
            "old":         len(old_ids),
            "new":         len(new_ids),
            "lost":        sorted(old_ids - new_ids),
            "resurrected": sorted(new_ids - old_ids),
            "at":          _now_iso(),
        }
        # Durable verdict: a dropped log line must not hide a lossy migration. This row is
        # queryable via get_migration_status / the admin endpoint, independent of logs.
        con.execute("INSERT OR REPLACE INTO store_meta (k, v) VALUES ('migration_check', ?)",
                    (json.dumps(payload),))
        con.commit()
        if ok:
            print(f"[commitments_store] migration verified dir={name} "
                  f"visible={len(new_ids)} (lossless)")
        else:
            print(f"[commitments_store] ⚠️ MIGRATION MISMATCH dir={name} "
                  f"old={len(old_ids)} new={len(new_ids)} "
                  f"lost={payload['lost']} resurrected={payload['resurrected']} "
                  f"— legacy JSON preserved; this user's store can be rolled back")
        return ok
    except Exception as e:
        print(f"[commitments_store] migration self-check skipped: {e}")
        try:
            con.execute("INSERT OR REPLACE INTO store_meta (k, v) VALUES ('migration_check', ?)",
                        (json.dumps({"verdict": "skipped", "error": str(e), "at": _now_iso()}),))
            con.commit()
        except Exception:
            pass
        return True


def _ensure_row(con, cid: str, now: str) -> None:
    """Insert a minimal placeholder row for a status-only id (e.g. a done id no longer in the
    snapshot) so re-extraction can't resurrect it."""
    con.execute(
        "INSERT OR IGNORE INTO commitments (id, type, description, status, first_seen, last_seen) "
        "VALUES (?, 'my_commitment', '', 'open', ?, ?)", (cid, now, now))


def _insert_content(con, it: dict, now: str) -> None:
    con.execute(f"""
        INSERT INTO commitments (id, {', '.join(_CONTENT_COLS)}, status, first_seen, last_seen)
        VALUES (?, {', '.join('?' for _ in _CONTENT_COLS)}, 'open', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            {', '.join(f'{c}=excluded.{c}' for c in _CONTENT_COLS)},
            last_seen=excluded.last_seen
    """, (it.get("id"), *_content_values(it), now, now))


def _content_values(it: dict) -> tuple:
    return (
        it.get("type", "my_commitment"), it.get("description", ""), it.get("due_date"),
        it.get("due_date_confidence", "none"), it.get("contact_email", ""),
        it.get("contact_name", ""), it.get("email_id", ""), it.get("subject", ""),
        it.get("received", ""), it.get("priority", "medium"),
        json.dumps(it.get("contact")) if it.get("contact") is not None else None,
        json.dumps(it.get("project")) if it.get("project") is not None else None,
    )


# ── write path (extraction) ─────────────────────────────────────────────────

def upsert_commitments(data_dir, items: list[dict]) -> None:
    """Persist extracted items, PRESERVING existing status (done/snoozed/asked) on conflict —
    the status columns are never in the upsert's write set. New ids start 'open'."""
    con = _conn(data_dir)
    try:
        now = _now_iso()
        for it in items or []:
            if it.get("id"):
                _insert_content(con, it, now)
        con.commit()
    finally:
        con.close()


def mark_email_processed(data_dir, email_id: str, received: str,
                         raw_commitments: list, msg_meta: dict = None) -> None:
    con = _conn(data_dir)
    try:
        con.execute(
            "INSERT OR REPLACE INTO processed_emails "
            "(email_id, received, extracted_at, raw_extraction_json, msg_meta_json) "
            "VALUES (?,?,?,?,?)",
            (email_id, received, _now_iso(), json.dumps(raw_commitments or []),
             json.dumps(msg_meta or {})))
        con.commit()
    finally:
        con.close()


def get_last_processed(data_dir) -> str:
    con = _conn(data_dir)
    try:
        row = con.execute("SELECT MAX(received) AS m FROM processed_emails").fetchone()
        return (row["m"] if row and row["m"] else "")
    finally:
        con.close()


def get_processed_ids(data_dir) -> set:
    con = _conn(data_dir)
    try:
        return {r["email_id"] for r in con.execute("SELECT email_id FROM processed_emails")}
    finally:
        con.close()


def get_raw_extractions(data_dir) -> list[dict]:
    """All cached raw extractions for cross-run dedup (replaces flatten_commitments)."""
    con = _conn(data_dir)
    try:
        out = []
        for r in con.execute("SELECT email_id, received, raw_extraction_json, msg_meta_json "
                             "FROM processed_emails"):
            msg = json.loads(r["msg_meta_json"] or "{}")
            for raw in json.loads(r["raw_extraction_json"] or "[]"):
                out.append({"_email_id": r["email_id"], "_received": r["received"],
                            "_msg": msg, **raw})
        return out
    finally:
        con.close()


def prune_processed(data_dir, days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = _conn(data_dir)
    try:
        cur = con.execute("DELETE FROM processed_emails WHERE received < ?", (cutoff,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


# ── mutations (status) — each ends with write_projection (chokepoint) ────────

def _set_status(data_dir, cid: str, **cols) -> bool:
    con = _conn(data_dir)
    try:
        _ensure_row(con, cid, _now_iso())
        sets = ", ".join(f"{k}=?" for k in cols)
        cur = con.execute(f"UPDATE commitments SET {sets} WHERE id=?",
                          (*cols.values(), cid))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def mark_done(data_dir, cid: str, method: str = "user") -> None:
    _set_status(data_dir, cid, status="done", status_at=_now_iso(), status_method=method,
                asked_expires_at=None, snoozed_until=None)
    write_projection(data_dir)


def mark_dismissed(data_dir, cid: str, method: str = "user_dismissed") -> None:
    _set_status(data_dir, cid, status="dismissed", status_at=_now_iso(), status_method=method,
                asked_expires_at=None, snoozed_until=None)
    write_projection(data_dir)


def mark_snoozed(data_dir, cid: str, days: int = 3) -> None:
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    _set_status(data_dir, cid, status="snoozed", status_at=_now_iso(), snoozed_until=until,
                asked_expires_at=None)
    write_projection(data_dir)


def mark_asked(data_dir, cid: str, expire_hours: int = 24) -> None:
    now = datetime.now(timezone.utc)
    # don't re-ask a resolved item
    con = _conn(data_dir)
    try:
        row = con.execute("SELECT status FROM commitments WHERE id=?", (cid,)).fetchone()
        if row and row["status"] in ("done", "dismissed"):
            return
    finally:
        con.close()
    _set_status(data_dir, cid, asked_at=now.isoformat(),
                asked_expires_at=(now + timedelta(hours=expire_hours)).isoformat())


def expire_asked(data_dir) -> list[str]:
    """Move expired 'asked' items to done (method=auto_expired). Returns affected ids."""
    con = _conn(data_dir)
    try:
        now = _now_iso()
        rows = con.execute(
            "SELECT id FROM commitments WHERE status='open' AND asked_expires_at IS NOT NULL "
            "AND asked_expires_at < ?", (now,)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            con.execute(
                "UPDATE commitments SET status='done', status_at=?, status_method='auto_expired', "
                "asked_expires_at=NULL WHERE status='open' AND asked_expires_at IS NOT NULL "
                "AND asked_expires_at < ?", (now, now))
            con.commit()
        return ids
    finally:
        con.close()


def mark_done_by_email_id(data_dir, email_id: str, method: str = "email_monitor") -> int:
    con = _conn(data_dir)
    try:
        cur = con.execute(
            "UPDATE commitments SET status='done', status_at=?, status_method=?, "
            "asked_expires_at=NULL, snoozed_until=NULL WHERE email_id=? AND status='open'",
            (_now_iso(), method, email_id))
        con.commit()
        n = cur.rowcount
    finally:
        con.close()
    if n:
        write_projection(data_dir)
    return n


# ── read path (queries) ─────────────────────────────────────────────────────

def _visible_clause(today: str) -> tuple[str, tuple]:
    # mirrors commitments_state.should_show: hide done/dismissed; hide active 'asked';
    # hide snoozed until the snooze date passes.
    return (
        "((status='open' AND asked_expires_at IS NULL) "
        " OR (status='snoozed' AND (snoozed_until IS NULL OR snoozed_until < ?)))",
        (today,),
    )


def _row_to_item(r) -> dict:
    it = {
        "id": r["id"], "type": r["type"], "description": r["description"],
        "due_date": r["due_date"], "due_date_confidence": r["due_date_confidence"],
        "contact_email": r["contact_email"], "contact_name": r["contact_name"],
        "email_id": r["email_id"], "subject": r["subject"], "received": r["received"],
        "priority": r["priority"] or "medium",
        "contact": json.loads(r["contact_json"]) if r["contact_json"] else None,
        "project": json.loads(r["project_json"]) if r["project_json"] else None,
    }
    if r["asked_expires_at"]:
        it["_asked"] = True
    return it


def query_visible(data_dir, today: str = None) -> list[dict]:
    today = today or today_local_str(data_dir)
    where, params = _visible_clause(today)
    con = _conn(data_dir)
    try:
        rows = con.execute(
            f"SELECT * FROM commitments WHERE {where} "
            "ORDER BY (type='their_commitment'), "
            "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "COALESCE(due_date,'9999-99-99')", params).fetchall()
        return [_row_to_item(r) for r in rows]
    finally:
        con.close()


def query_due_today(data_dir, today: str = None) -> list[dict]:
    today = today or today_local_str(data_dir)
    where, params = _visible_clause(today)
    con = _conn(data_dir)
    try:
        rows = con.execute(
            f"SELECT * FROM commitments WHERE type='my_commitment' AND due_date=? AND {where} "
            "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, received",
            (today, *params)).fetchall()
        return [_row_to_item(r) for r in rows]
    finally:
        con.close()


def query_upcoming(data_dir, today: str, cutoff: str) -> list[dict]:
    """Base visible my_commitments with a due_date <= cutoff (overdue included). Caller merges
    meeting action items + computes overdue flags (those aren't store-owned)."""
    where, params = _visible_clause(today)
    con = _conn(data_dir)
    try:
        rows = con.execute(
            f"SELECT * FROM commitments WHERE type='my_commitment' AND due_date IS NOT NULL "
            f"AND due_date<=? AND {where}", (cutoff, *params)).fetchall()
        return [_row_to_item(r) for r in rows]
    finally:
        con.close()


def get_hidden_ids(data_dir, today: str = None) -> set:
    """Commitment ids that exist but are NOT currently visible (done/dismissed/asked/snoozed).
    Used to prune the JSON projection — items whose id isn't a store commitment (e.g. merged
    meeting items) are left untouched by the caller."""
    today = today or today_local_str(data_dir)
    where, params = _visible_clause(today)
    con = _conn(data_dir)
    try:
        all_ids = {r["id"] for r in con.execute("SELECT id FROM commitments")}
        vis = {r["id"] for r in con.execute(
            f"SELECT id FROM commitments WHERE {where}", params)}
        return all_ids - vis
    finally:
        con.close()


def get_open_ids(data_dir) -> set:
    return {it["id"] for it in query_visible(data_dir)}


def get_asked_ids(data_dir) -> list:
    """Ids currently in a check-in ('asked') window — used by the 'mark/skip all' branch."""
    con = _conn(data_dir)
    try:
        return [r["id"] for r in con.execute(
            "SELECT id FROM commitments WHERE status='open' AND asked_expires_at IS NOT NULL")]
    finally:
        con.close()


def get_migration_status(data_dir) -> dict:
    """Read-only migration verdict for a user. Deliberately does NOT use _conn (which would
    trigger the migration) — opens a raw connection so the admin endpoint can REPORT status
    without changing it. States: not_accessed (no store.db) / no_flag / migrated_unchecked /
    checked (with verdict=lossless|mismatch|skipped + counts)."""
    import sqlite3
    path = _db_path(data_dir)
    if not path.exists():
        return {"state": "not_accessed"}
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        mig = con.execute("SELECT v FROM store_meta WHERE k='migrated_from_json'").fetchone()
        chk = con.execute("SELECT v FROM store_meta WHERE k='migration_check'").fetchone()
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


# ── projection (keep the legacy JSON files in sync for the dashboard/recap) ───

def write_projection(data_dir) -> None:
    """Regenerate commitments_extract.json from the store; prune now-hidden commitment ids out
    of due_today.json / upcoming_commitments.json (a mutation only ever REMOVES items, so a
    prune is sufficient and preserves AI-filter / meeting-merge results + non-store items)."""
    from src.storage import atomic_write_json
    data_dir = Path(data_dir)
    try:
        today = today_local_str(data_dir)
        visible = query_visible(data_dir, today)
        atomic_write_json(data_dir / "results" / "commitments_extract.json", {
            "id": "commitments_extract", "status": "fresh", "last_run": _now_iso(),
            "items": visible, "count": len(visible), "empty": not visible,
        })
        # Status projection (rollback safety): keep commitments_state.json fully in sync so a
        # revert + `rm store.db` resumes from current data with zero loss. The DB is the only
        # writer of truth; this JSON is a derived read-model, not an independent writer.
        con = _conn(data_dir)
        try:
            st = {"done": {}, "asked": {}, "snoozed": {}}
            for r in con.execute("SELECT id, status, status_at, status_method, snoozed_until, "
                                 "asked_at, asked_expires_at FROM commitments"):
                if r["status"] in ("done", "dismissed"):
                    st["done"][r["id"]] = {"at": r["status_at"] or _now_iso(),
                                           "method": r["status_method"] or "user"}
                elif r["status"] == "snoozed" and r["snoozed_until"]:
                    st["snoozed"][r["id"]] = {"until": r["snoozed_until"]}
                if r["asked_expires_at"]:
                    st["asked"][r["id"]] = {"asked_at": r["asked_at"],
                                            "expires_at": r["asked_expires_at"]}
        finally:
            con.close()
        atomic_write_json(data_dir / "commitments_state.json", st)
        hidden = get_hidden_ids(data_dir, today)
        for name in ("due_today.json", "upcoming_commitments.json"):
            p = data_dir / "results" / name
            data = _read_json(p)
            items = data.get("items")
            if not isinstance(items, list):
                continue
            kept = [it for it in items if it.get("id") not in hidden]
            if len(kept) != len(items):
                data["items"] = kept
                data["count"] = len(kept)
                data["empty"] = not kept
                atomic_write_json(p, data)
    except Exception as e:
        print(f"[commitments_store] write_projection failed: {e}")
