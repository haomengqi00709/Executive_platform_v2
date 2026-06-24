"""F3 (pointer navigation): open_email follows a stored email_id back to the full original; and
dismiss_email_followup now carries the email_id into the handled annotation so it's navigable."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_openmail_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot_tools.email.open_email.tool import build as build_open          # noqa: E402


class _FakeGraph:
    def get_message(self, mid):
        return {
            "id": mid, "subject": "MEP Ai Tools",
            "from": {"emailAddress": {"address": "daniel@imodel3d.com"}},
            "toRecipients": [{"emailAddress": {"address": "jason@x.com"}}],
            "receivedDateTime": "2026-06-18T10:00:00Z",
            "body": {"contentType": "text", "content": "Here is the full original body. " * 10},
        }


def _ctx(tmp_path, graph=None):
    return SimpleNamespace(data_dir=tmp_path, settings={}, state={}, owner_graph=graph)


def test_open_email_returns_full_original(tmp_path):
    out = json.loads(build_open(_ctx(tmp_path, _FakeGraph()))("AAMk-123"))
    assert out["email_id"] == "AAMk-123"
    assert out["subject"] == "MEP Ai Tools" and out["from"] == "daniel@imodel3d.com"
    assert "full original body" in out["body"]


def test_open_email_empty_id(tmp_path):
    assert "email_id" in build_open(_ctx(tmp_path, _FakeGraph()))("")


def test_open_email_no_owner_graph(tmp_path):
    assert "not available" in build_open(_ctx(tmp_path, None))("AAMk-123")


def test_open_email_body_capped(tmp_path):
    class Big:
        def get_message(self, mid):
            return {"id": mid, "subject": "x", "from": {}, "toRecipients": [],
                    "body": {"contentType": "text", "content": "z" * 9000}}
    out = json.loads(build_open(_ctx(tmp_path, Big()))("id1"))
    assert out["body_truncated"] is True and len(out["body"]) == 4000


def test_open_email_resolves_commitment_id_to_email_id(tmp_path):
    """The model often passes a commitment's id, not its email_id. open_email must follow the
    pointer: commitment id → that commitment's source email_id → fetch the original."""
    from src.modules import commitments_store as cstore
    cstore.upsert_commitments(tmp_path, [{
        "id": "cf70c4b89d3d291a", "type": "their_commitment", "description": "Daniel to send X",
        "email_id": "AAMk-REAL-789", "subject": "Re: Follow-up", "received": "2026-06-23T07:51:00Z",
        "priority": "medium"}])

    seen = {}
    class Capture:
        def get_message(self, mid):
            seen["id"] = mid
            return {"id": mid, "subject": "Re: Follow-up", "from": {}, "toRecipients": [],
                    "body": {"contentType": "text", "content": "the real body"}}
    out = json.loads(build_open(_ctx(tmp_path, Capture()))("cf70c4b89d3d291a"))   # passed the COMMITMENT id
    assert seen["id"] == "AAMk-REAL-789"          # resolved to the real email_id before fetching
    assert "real body" in out["body"]


def test_dismiss_followup_records_email_id(tmp_path):
    """The handled annotation must carry the email_id so it's navigable via open_email."""
    from src.bot_tools.email.dismiss_email_followup.tool import build as build_dismiss
    from src.modules import email_store
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "followup_needed.json").write_text(json.dumps({
        "id": "followup_needed", "status": "fresh", "items": [
            {"email_id": "SENT-789", "conversation_id": "CONV-1", "to_email": "daniel@trustai.com",
             "to_name": "Daniel", "subject": "Testing"}], "count": 1}))
    out = build_dismiss(_ctx(tmp_path))("daniel")
    assert "Dismissed 1" in out
    handled = email_store.get_handled_map(tmp_path, kinds=email_store.FOLLOWUP_KINDS)
    from src.modules.subject_match import normalize_subject
    entry = handled[("daniel@trustai.com", normalize_subject("Testing"))]
    assert entry["email_id"] == "SENT-789" and entry["conversation_id"] == "CONV-1"
