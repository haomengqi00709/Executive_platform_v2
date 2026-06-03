"""Bot/owner lifecycle: the 'zombie bot flag' fix.

Regression for the i3d Daniel incident: an owner account that got
is_registered_bot=True with owner_uid=None (a 'zombie') was permanently skipped
by every per-user event poll, so his meeting recordings never processed.

These tests need no real OAuth/Teams — they exercise pure helpers + file state
under a temp DATA_DIR.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Point DATA_DIR at a temp dir BEFORE importing the app (server.py mkdirs it on
# import). Force-override any inherited DATA_DIR (e.g. the container's /app/.data,
# which is read-only here). Per-test isolation is done by monkeypatching auth.DATA_DIR.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ceo_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import auth          # noqa: E402
from src import server        # noqa: E402


def _mk_account(data_dir: Path, uid: str, bot_state: dict | None):
    (data_dir / "_sessions").mkdir(parents=True, exist_ok=True)
    (data_dir / "_sessions" / f"{uid}.json").write_text(json.dumps({"username": f"{uid}@x.com"}))
    (data_dir / uid).mkdir(parents=True, exist_ok=True)
    if bot_state is not None:
        (data_dir / uid / "teams_bot.json").write_text(json.dumps(bot_state))


def test_is_bound_bot_predicate():
    assert server._is_bound_bot({"is_registered_bot": True, "owner_uid": "boss"}) is True   # real bound bot
    assert server._is_bound_bot({"is_registered_bot": True, "owner_uid": None}) is False     # zombie
    assert server._is_bound_bot({"is_registered_bot": True}) is False                        # zombie (no owner key)
    assert server._is_bound_bot({"owner_uid": "boss"}) is False                              # not a registered bot
    assert server._is_bound_bot({}) is False                                                 # plain owner


def test_event_polls_treat_zombie_as_owner(tmp_path, monkeypatch):
    """The Daniel regression: event polls skip iff _is_bound_bot — a zombie owner
    must be processed (not skipped), a real bound bot must be skipped."""
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    _mk_account(tmp_path, "daniel", {"is_registered_bot": True, "enabled": True, "owner_uid": None})
    _mk_account(tmp_path, "audrey", {"is_registered_bot": True, "enabled": True, "owner_uid": "daniel"})

    daniel = server._read_json(server._bot_state_path("daniel"))
    audrey = server._read_json(server._bot_state_path("audrey"))
    assert server._is_bound_bot(daniel) is False   # processed as owner -> recordings scanned
    assert server._is_bound_bot(audrey) is True     # skipped as a real bot


def test_startup_heal_resets_only_zombies(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    _mk_account(tmp_path, "zombie",  {"is_registered_bot": True, "enabled": True, "owner_uid": None})
    _mk_account(tmp_path, "realbot", {"is_registered_bot": True, "enabled": True, "owner_uid": "boss"})
    _mk_account(tmp_path, "owner",   None)  # plain owner, no teams_bot.json

    server._heal_zombie_bot_flags_at_startup()

    z = json.loads((tmp_path / "zombie" / "teams_bot.json").read_text())
    assert z["is_registered_bot"] is False and z["enabled"] is False        # healed -> clean owner
    rb = json.loads((tmp_path / "realbot" / "teams_bot.json").read_text())
    assert rb["is_registered_bot"] is True and rb["owner_uid"] == "boss"    # untouched


def test_unbind_clears_registration_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    _mk_account(tmp_path, "owner1", None)
    _mk_account(tmp_path, "bot1", {"is_registered_bot": True, "enabled": True,
                                   "owner_uid": "owner1", "chat_id": "c"})
    (tmp_path / "owner1" / "bot_link.json").write_text(json.dumps({"bot_uid": "bot1"}))

    server._unbind_bot_from_user("owner1")

    bs = json.loads((tmp_path / "bot1" / "teams_bot.json").read_text())
    assert bs["is_registered_bot"] is False   # symmetric teardown
    assert bs["owner_uid"] is None
