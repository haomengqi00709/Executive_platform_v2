"""forward_file must create a Drafts email with the file attached and NEVER send (Drafts-only rule),
and must consume the pending_file handle so it isn't re-forwarded."""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_ff_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_forward_file():
    spec = importlib.util.spec_from_file_location(
        "forward_file_tool",
        str(Path(__file__).resolve().parents[1] / "src" / "bot_tools" / "files" / "forward_file" / "tool.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGraph:
    def __init__(self):
        self.calls = []

    def download(self, ep):
        self.calls.append(("download", ep)); return b"FILEBYTES"

    def create_draft(self, subject, body, to, mailbox=None):
        self.calls.append(("create_draft", to, subject)); return {"id": "msg1", "webLink": "http://draft"}

    def add_file_attachment(self, message_id, filename, content, mime="x"):
        self.calls.append(("add_file_attachment", message_id, filename, len(content))); return {"id": "att1"}

    def send_mail(self, *a, **k):
        self.calls.append(("send_mail",))   # must NEVER be called


class Ctx:
    def __init__(self, graph, state, data_dir):
        self.owner_graph = graph; self.graph = graph
        self.state = state; self.data_dir = data_dir


def test_forward_file_stages_draft_with_attachment_never_sends(tmp_path):
    g = FakeGraph()
    state = {"pending_file": {"filename": "invoice.pdf", "mime": "application/pdf",
                              "onedrive_path": "CEO Platform/Inbox/invoice.pdf"}}
    fn = _load_forward_file().build(Ctx(g, state, tmp_path))
    out = fn(to="bob@acme.com")
    kinds = [c[0] for c in g.calls]
    assert "create_draft" in kinds and "add_file_attachment" in kinds
    assert "send_mail" not in kinds            # Drafts-only rule — never auto-send
    assert state["pending_file"] is None       # handle consumed
    assert "bob@acme.com" in out


def test_forward_file_no_pending_file_is_a_no_op(tmp_path):
    g = FakeGraph()
    fn = _load_forward_file().build(Ctx(g, {}, tmp_path))
    out = fn(to="bob@acme.com")
    assert "no file" in out.lower()
    assert g.calls == []                        # nothing created when there's nothing to forward
