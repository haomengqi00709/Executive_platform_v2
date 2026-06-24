"""CRM store (Phase 3a of the single-store migration).

Brings the per-user contact database into the shared store.db (same file as commitments/email,
separate tables). The WIN: per-contact rows with atomic transactional writes — the daily CRM
rebuild, the bot's update_contact, the server PATCH, and m03 all wrote the SAME whole crm.json,
so a long (minutes) rebuild could lose a concurrent edit (whole-file read-modify-write race, the
token-cache class of bug). Here each contact is its own row; the edit-preserving upsert re-merges
against the CURRENT row, so a concurrent user edit is never clobbered.

DATA-LOSS PREVENTION (Daniel has heavy customization — must not lose it):
  1. One-time lazy import is LOSSLESS — every field of every contact carried over verbatim,
     crm.json kept as a synced projection + backup, reversible.
  2. The build/refresh upsert is EDIT-PRESERVING — it reuses crm._merge_ai_enrichment (AI value
     wins only if non-empty; user columns never written) re-merged against the live row, so
     notes/tags/priority/ignore/archived/draft_link/meeting_ids/manual/source/added_at survive
     every AI rebuild.

Contacts are stored as a JSON blob per row (lossless, reuses the proven merge fn). last_scan /
months_scanned live in crm_meta. Readers keep reading the crm.json projection (write_projection
keeps it synced) — no reader change required.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.modules.db_helpers import open_sqlite
# Top-level import is safe: crm.py must import crm_store ONLY via deferred (in-function) imports,
# so this direction does not create a cycle.
from src.modules.crm import _merge_ai_enrichment

# Fields the daily build/refresh is allowed to write onto a contact (in addition to the AI-owned
# fields handled by _merge_ai_enrichment). Everything NOT here is a user/other-module column and
# is preserved from the live row.
_DERIVED_FIELDS = ("thread_count", "last_contact", "name")


def _db_path(data_dir) -> Path:
    return Path(data_dir) / "store.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(data_dir):
    path = _db_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_sqlite(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS contacts (email TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS crm_meta (k TEXT PRIMARY KEY, v TEXT)")
    con.commit()
    _maybe_import(con, data_dir)
    return con


# ── one-time lazy migration from crm.json ────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _maybe_import(con, data_dir) -> None:
    row = con.execute("SELECT v FROM crm_meta WHERE k='migrated_from_json'").fetchone()
    if row:
        if not con.execute("SELECT v FROM crm_meta WHERE k='migration_check'").fetchone():
            _verify_import(con, data_dir)   # backfill verdict for an already-migrated user
        return
    data_dir = Path(data_dir)
    crm = _read_json(data_dir / "crm.json")
    contacts = crm.get("contacts") or {}
    now = _now_iso()
    try:
        for email, contact in contacts.items():
            if not email:
                continue
            con.execute("INSERT OR REPLACE INTO contacts (email, data, updated_at) VALUES (?,?,?)",
                        (email.lower(), json.dumps(contact, ensure_ascii=False), now))
        con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('last_scan', ?)",
                    (json.dumps(crm.get("last_scan")),))
        con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('months_scanned', ?)",
                    (json.dumps(crm.get("months_scanned", 0)),))
    except Exception as e:
        print(f"[crm_store] import skipped/failed: {e}")
    con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('migrated_from_json', ?)", (now,))
    con.commit()
    _verify_import(con, data_dir)


def _verify_import(con, data_dir: Path) -> bool:
    """Lossless self-check: the store's contact set must equal crm.json's, field-for-field. Writes
    a durable verdict to crm_meta (logs can be dropped under load) + logs it. Best-effort."""
    try:
        crm = _read_json(Path(data_dir) / "crm.json")
        json_contacts = {k.lower(): v for k, v in (crm.get("contacts") or {}).items()}
        store_contacts = {r["email"]: json.loads(r["data"]) for r in con.execute("SELECT email, data FROM contacts")}
        missing = sorted(set(json_contacts) - set(store_contacts))   # in JSON, lost in store
        # field-level loss check on shared contacts
        field_loss = []
        for e in (set(json_contacts) & set(store_contacts)):
            jc, sc = json_contacts[e], store_contacts[e]
            for f, v in jc.items():
                if v not in (None, "", [], {}) and sc.get(f) != v:
                    field_loss.append(f"{e}.{f}")
        ok = not missing and not field_loss
        name = Path(data_dir).name
        payload = {"verdict": "lossless" if ok else "mismatch", "json": len(json_contacts),
                   "store": len(store_contacts), "lost": missing[:20],
                   "field_loss": field_loss[:20], "at": _now_iso()}
        con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('migration_check', ?)",
                    (json.dumps(payload),))
        con.commit()
        if ok:
            print(f"[crm_store] migration verified dir={name} contacts={len(store_contacts)} (lossless)")
        else:
            print(f"[crm_store] ⚠️ CRM MIGRATION MISMATCH dir={name} json={len(json_contacts)} "
                  f"store={len(store_contacts)} lost={missing[:20]} field_loss={field_loss[:20]} "
                  f"— crm.json preserved; rollback possible")
        return ok
    except Exception as e:
        print(f"[crm_store] migration self-check skipped: {e}")
        return True


# ── write path: edit-preserving upsert (build/refresh) ───────────────────────

def upsert_built_contacts(data_dir, built: dict) -> None:
    """Persist freshly-built contacts from build_crm/refresh_crm, PRESERVING user edits.

    `built` = {email: full_contact_dict} as produced by the rebuild. For each, we re-merge
    against the CURRENT store row (NOT the rebuild's minutes-stale snapshot) so a concurrent
    bot/UI edit to user columns is never lost:
      - AI columns: from `built` (via _merge_ai_enrichment — non-empty wins, else keep current)
      - derived (thread_count / last_contact / name): from `built` (last_contact = max)
      - everything else (user columns): kept from the current row
    """
    con = _conn(data_dir)
    try:
        now = _now_iso()
        for email, fresh in (built or {}).items():
            if not email:
                continue
            e = email.lower()
            r = con.execute("SELECT data FROM contacts WHERE email=?", (e,)).fetchone()
            cur = json.loads(r["data"]) if r else {}
            merged = _merge_ai_enrichment(cur, fresh)   # AI cols + preserve all non-AI user cols
            # derived (scan-authoritative) fields — not AI-owned, so apply explicitly
            if fresh.get("thread_count") is not None:
                merged["thread_count"] = fresh["thread_count"]
            if fresh.get("last_contact"):
                merged["last_contact"] = max(merged.get("last_contact", ""), fresh["last_contact"])
            if not merged.get("name") and fresh.get("name"):
                merged["name"] = fresh["name"]
            merged.setdefault("email", e)
            con.execute("INSERT OR REPLACE INTO contacts (email, data, updated_at) VALUES (?,?,?)",
                        (e, json.dumps(merged, ensure_ascii=False), now))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)


def update_contact_field(data_dir, email: str, field: str, value) -> dict:
    """User edit of one field (notes appends with a date stamp; everything else overwrites).
    Mirrors crm.update_contact exactly, but per-row + atomic. Creates the contact if absent."""
    e = (email or "").lower()
    con = _conn(data_dir)
    try:
        r = con.execute("SELECT data FROM contacts WHERE email=?", (e,)).fetchone()
        contact = json.loads(r["data"]) if r else {}
        if field == "notes":
            existing = contact.get("notes", "")
            stamp = datetime.now().strftime("%Y-%m-%d")
            contact["notes"] = f"{existing}\n[{stamp}] {value}".strip()
        else:
            contact[field] = value
        contact.setdefault("email", e)
        con.execute("INSERT OR REPLACE INTO contacts (email, data, updated_at) VALUES (?,?,?)",
                    (e, json.dumps(contact, ensure_ascii=False), _now_iso()))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)
    return contact


def replace_from_dict(data_dir, crm: dict) -> None:
    """Whole-dict save path (the chokepoint behind crm.save_crm — used by build/refresh/bulk/tag/
    server/m03). Upserts every contact as a full row + sets scan meta, then regenerates the crm.json
    projection. UPSERT-ONLY (never deletes a row) — CRM doesn't hard-delete contacts and no caller
    passes a shrunk dict, so never-deleting is the safe default against a buggy partial-dict caller.
    Edit-preservation for the AI rebuild is handled UPSTREAM by crm._merge_ai_enrichment (parity with
    the prior whole-file crm.json behaviour); race-safe re-merge is available via upsert_built_contacts."""
    contacts = (crm or {}).get("contacts") or {}
    con = _conn(data_dir)
    try:
        now = _now_iso()
        for email, contact in contacts.items():
            if not email:
                continue
            con.execute("INSERT OR REPLACE INTO contacts (email, data, updated_at) VALUES (?,?,?)",
                        (email.lower(), json.dumps(contact, ensure_ascii=False), now))
        if "last_scan" in (crm or {}):
            con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('last_scan', ?)",
                        (json.dumps(crm.get("last_scan")),))
        if "months_scanned" in (crm or {}):
            con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('months_scanned', ?)",
                        (json.dumps(crm.get("months_scanned", 0)),))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)


def clear(data_dir) -> None:
    """Drop all contacts + meta (used by the onboarding reset/cleanup endpoints, which delete
    crm.json to rebuild from scratch). Without this, the upsert-only replace_from_dict would leave
    pre-reset rows behind. The next store access re-imports from the (now empty/absent) JSON."""
    path = _db_path(data_dir)
    if not path.exists():
        return
    con = open_sqlite(path)
    try:
        con.execute("DROP TABLE IF EXISTS contacts")
        con.execute("DROP TABLE IF EXISTS crm_meta")
        con.commit()
    finally:
        con.close()


def set_scan_meta(data_dir, last_scan, months_scanned) -> None:
    con = _conn(data_dir)
    try:
        con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('last_scan', ?)", (json.dumps(last_scan),))
        con.execute("INSERT OR REPLACE INTO crm_meta (k, v) VALUES ('months_scanned', ?)", (json.dumps(months_scanned),))
        con.commit()
    finally:
        con.close()
    write_projection(data_dir)


# ── read path ────────────────────────────────────────────────────────────────

def _meta(con, key, default=None):
    r = con.execute("SELECT v FROM crm_meta WHERE k=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except Exception:
        return default


def load_crm(data_dir) -> dict:
    """Return the crm.json-shaped dict from the store (drop-in for crm.load_crm)."""
    con = _conn(data_dir)
    try:
        contacts = {r["email"]: json.loads(r["data"]) for r in con.execute("SELECT email, data FROM contacts")}
        return {"last_scan": _meta(con, "last_scan"), "months_scanned": _meta(con, "months_scanned", 0),
                "contacts": contacts}
    finally:
        con.close()


def get_ignored_emails(data_dir) -> set:
    """Emails of contacts with ignore=True or archived=True — fed to the screener (replaces the
    inline scan in email_monitor.py)."""
    con = _conn(data_dir)
    try:
        out = set()
        for r in con.execute("SELECT email, data FROM contacts"):
            c = json.loads(r["data"])
            if c.get("ignore") or c.get("archived"):
                out.add(r["email"])
        return out
    finally:
        con.close()


def write_projection(data_dir) -> None:
    """Regenerate crm.json from the store so every existing reader (sections, screener, tools,
    find_*, list_groups) keeps working unchanged. Best-effort, atomic."""
    try:
        crm = load_crm(data_dir)
        p = Path(data_dir) / "crm.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(crm, indent=2, ensure_ascii=False))
        tmp.replace(p)
    except Exception as e:
        print(f"[crm_store] projection write failed: {e}")


def get_migration_status(data_dir) -> dict:
    """Read-only verdict for the admin endpoint — does NOT trigger migration."""
    path = _db_path(data_dir)
    if not path.exists():
        return {"state": "not_accessed"}
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        try:
            mig = con.execute("SELECT v FROM crm_meta WHERE k='migrated_from_json'").fetchone()
            chk = con.execute("SELECT v FROM crm_meta WHERE k='migration_check'").fetchone()
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
