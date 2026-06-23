"""Email subsystem store (Phase 2 of the single-store migration).

Two concerns, both in the per-user store.db (same file as commitments_store, separate tables):

1. **Poller state** (`email_state` table) — the dedup/timing dict that email_monitor.py keeps
   (processed_conv_ids / seen_msg_ids / realtime_pushed_ids / last_*_ts / last_notified_emails /
   pending_priority_followup). Previously a whole-file JSON that the email poll AND the bot's
   dismiss tool both rewrote → read-modify-write corruption risk (token-cache class of bug).
   Here it's a single JSON blob written inside a SQLite transaction (atomic + serialized, no
   torn writes). A projection back to email_monitor.json keeps legacy readers working.

2. **Durable handled annotations** (`email_handled` table) — when the user drafts/sends a reply,
   we record (counterparty, normalized-subject) → handled. reply_needed consults this so an email
   the user already acted on does NOT reappear just because the live Graph draft/sent scan missed
   it (pagination / subfolder / timing). This is the persistent form of the fragile subject-match
   channel — it fixes "I drafted a reply but the email still shows".

Mirrors commitments_store conventions: lazy one-time import, JSON kept as projection/backup,
short transactions, no AI/Graph calls inside a transaction.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.modules.db_helpers import open_sqlite
from src.modules.subject_match import normalize_subject

_DEFAULT_POLLER = {
    "last_checked_ts": "",
    "last_digest_ts": "",
    "last_expiry_warning_date": "",
    "processed_conv_ids": [],
    "pending_priority_followup": [],
    "last_notified_emails": [],
}


def _db_path(data_dir) -> Path:
    return Path(data_dir) / "store.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(data_dir):
    """Open the store, creating the email tables + running the one-time JSON import if needed.
    Independent of commitments_store: only touches email_* tables, never triggers the
    commitments migration."""
    path = _db_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = open_sqlite(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS email_state (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("""
        CREATE TABLE IF NOT EXISTS email_handled (
            counterparty    TEXT NOT NULL,
            norm_subject    TEXT NOT NULL,
            kind            TEXT NOT NULL,
            target_subject  TEXT,
            email_id        TEXT,
            conversation_id TEXT,
            handled_at      TEXT,
            source          TEXT,
            PRIMARY KEY (counterparty, norm_subject)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS ix_eh_conv ON email_handled(conversation_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_eh_at ON email_handled(handled_at)")
    con.commit()
    _maybe_import(con, data_dir)
    return con


def _maybe_import(con, data_dir) -> None:
    row = con.execute("SELECT v FROM email_state WHERE k='migrated_from_json'").fetchone()
    if row:
        return
    p = Path(data_dir) / "email_monitor.json"
    if p.exists():
        try:
            data = json.loads(p.read_text())
            con.execute("INSERT OR REPLACE INTO email_state (k, v) VALUES ('poller', ?)",
                        (json.dumps(data, ensure_ascii=False),))
        except Exception as e:
            print(f"[email_store] poller import skipped/failed: {e}")
    con.execute("INSERT OR REPLACE INTO email_state (k, v) VALUES ('migrated_from_json', ?)",
                (_now_iso(),))
    con.commit()


# ── poller state (Piece A) ───────────────────────────────────────────────────

def get_poller_state(data_dir) -> dict:
    con = _conn(data_dir)
    try:
        row = con.execute("SELECT v FROM email_state WHERE k='poller'").fetchone()
    finally:
        con.close()
    if not row:
        return json.loads(json.dumps(_DEFAULT_POLLER))  # fresh deep copy
    try:
        return json.loads(row["v"])
    except Exception:
        return json.loads(json.dumps(_DEFAULT_POLLER))


def save_poller_state(data_dir, state: dict) -> None:
    """Atomic transactional write (no torn whole-file JSON), then sync the legacy projection."""
    con = _conn(data_dir)
    try:
        con.execute("INSERT OR REPLACE INTO email_state (k, v) VALUES ('poller', ?)",
                    (json.dumps(state, ensure_ascii=False),))
        con.commit()
    finally:
        con.close()
    _write_projection(data_dir, state)


def _write_projection(data_dir, state: dict) -> None:
    """Keep email_monitor.json synced as a backup + for legacy readers (bot session context).
    Best-effort: the store is the source of truth."""
    try:
        p = Path(data_dir) / "email_monitor.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        tmp.replace(p)
    except Exception:
        pass


# ── durable handled annotations (Piece B) ────────────────────────────────────

def mark_handled(data_dir, *, counterparty: str, subject: str, kind: str = "drafted",
                 target_subject: str = "", email_id: str = "", conversation_id: str = "",
                 source: str = "bot") -> bool:
    """Record that the user acted on the email from `counterparty` with this `subject`
    (a reply subject like 'Re: X' normalizes to the original). Keyed by (counterparty,
    normalized-subject) so reply_needed can exclude it durably. Returns False if unkeyable."""
    cp = (counterparty or "").strip().lower()
    ns = normalize_subject(subject or "")
    if not cp or not ns:
        return False
    con = _conn(data_dir)
    try:
        con.execute(
            "INSERT OR REPLACE INTO email_handled "
            "(counterparty, norm_subject, kind, target_subject, email_id, conversation_id, handled_at, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cp, ns, kind, target_subject or subject, email_id, conversation_id, _now_iso(), source))
        con.commit()
    finally:
        con.close()
    return True


def get_handled_map(data_dir) -> dict:
    """{(counterparty, norm_subject): {kind, target_subject, email_id, conversation_id, handled_at}}
    — loaded once by reply_needed before its handled loop."""
    con = _conn(data_dir)
    try:
        out = {}
        for r in con.execute("SELECT * FROM email_handled"):
            out[(r["counterparty"], r["norm_subject"])] = {
                "kind": r["kind"], "target_subject": r["target_subject"],
                "email_id": r["email_id"], "conversation_id": r["conversation_id"],
                "handled_at": r["handled_at"],
            }
        return out
    finally:
        con.close()


def is_handled(data_dir, counterparty: str, subject: str) -> dict | None:
    cp = (counterparty or "").strip().lower()
    ns = normalize_subject(subject or "")
    if not cp or not ns:
        return None
    con = _conn(data_dir)
    try:
        r = con.execute(
            "SELECT kind, target_subject, handled_at FROM email_handled "
            "WHERE counterparty=? AND norm_subject=?", (cp, ns)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def overlay_handled(data_dir, items: list) -> tuple[list, list]:
    """Read-time overlay for reply_needed: split items into (still-open, now-handled) using the
    durable handled table. The expensive AI-computed list comes from the cached snapshot; THIS
    cheap live lookup removes any email the user already drafted/replied to — so it drops off
    immediately, without re-running the slow/costly Graph+AI section. Matched by
    (sender, normalized subject), the same key approve_draft writes."""
    handled = get_handled_map(data_dir)
    if not handled:
        return list(items or []), []
    open_items, now_handled = [], []
    for it in items or []:
        cp = (it.get("from_email") or "").strip().lower()
        key = (cp, normalize_subject(it.get("subject") or ""))
        if cp and key in handled:
            now_handled.append({**it, "_handled_kind": handled[key].get("kind") or "drafted"})
        else:
            open_items.append(it)
    return open_items, now_handled


def prune_handled(data_dir, days: int = 45) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = _conn(data_dir)
    try:
        n = con.execute("DELETE FROM email_handled WHERE handled_at < ?", (cutoff,)).rowcount
        con.commit()
        return n
    finally:
        con.close()
