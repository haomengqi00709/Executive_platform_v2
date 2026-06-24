"""F4c: a counterparty reply auto-clears the their_commitment for that thread, via a new
conversation_id column. Includes the additive-migration test (the live-table safety concern)."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_convclear_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import commitments_store as cs   # noqa: E402


def _c(cid, ctype, conv, desc="d", **kw):
    base = {"id": cid, "type": ctype, "description": desc, "conversation_id": conv,
            "email_id": f"e-{cid}", "priority": "medium"}
    base.update(kw)
    return base


def test_conversation_id_roundtrips(tmp_path):
    cs.upsert_commitments(tmp_path, [_c("x", "their_commitment", "CONV-Z")])
    item = [c for c in cs.query_visible(tmp_path) if c["id"] == "x"][0]
    assert item["conversation_id"] == "CONV-Z"


def test_reply_clears_their_commitment_only(tmp_path):
    cs.upsert_commitments(tmp_path, [
        _c("t1", "their_commitment", "CONV-A", "Daniel will send the proposal"),
        _c("m1", "my_commitment",   "CONV-A", "I will review it"),
        _c("t2", "their_commitment", "CONV-B", "Bob will send numbers")])
    n = cs.mark_done_by_conversation_id(tmp_path, "CONV-A")
    assert n == 1                                        # only the their_commitment in CONV-A
    ids = {c["id"] for c in cs.query_visible(tmp_path)}
    assert "t1" not in ids                               # cleared (done → hidden)
    assert "m1" in ids                                   # my_commitment in same thread untouched
    assert "t2" in ids                                   # their_commitment in another thread untouched


def test_clear_empty_conversation_is_noop(tmp_path):
    cs.upsert_commitments(tmp_path, [_c("t1", "their_commitment", "CONV-A")])
    assert cs.mark_done_by_conversation_id(tmp_path, "") == 0
    assert cs.mark_done_by_conversation_id(tmp_path, "CONV-NONE") == 0


def test_additive_migration_on_legacy_db(tmp_path):
    """A pre-F4c store (commitments table WITHOUT conversation_id) must migrate losslessly:
    the column is added, existing rows survive (conversation_id NULL), and queries keep working."""
    db = tmp_path / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("""
        CREATE TABLE commitments (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, description TEXT NOT NULL,
            due_date TEXT, due_date_confidence TEXT, contact_email TEXT, contact_name TEXT,
            email_id TEXT, subject TEXT, received TEXT, priority TEXT DEFAULT 'medium',
            contact_json TEXT, project_json TEXT, status TEXT NOT NULL DEFAULT 'open',
            status_at TEXT, status_method TEXT, snoozed_until TEXT, asked_expires_at TEXT,
            asked_at TEXT, first_seen TEXT, last_seen TEXT)""")
    con.execute("INSERT INTO commitments (id, type, description, email_id, status) "
                "VALUES ('old1','their_commitment','legacy commitment','e-old','open')")
    con.commit()
    con.close()

    # First access through the store runs the additive ALTER.
    items = cs.query_visible(tmp_path)
    old = [c for c in items if c["id"] == "old1"][0]
    assert old["conversation_id"] is None                # column added, existing row NULL (lossless)
    assert old["description"] == "legacy commitment"     # legacy data intact

    # New conversation-based clear works on rows written after the migration.
    cs.upsert_commitments(tmp_path, [_c("t1", "their_commitment", "CONV-NEW")])
    assert cs.mark_done_by_conversation_id(tmp_path, "CONV-NEW") == 1
