"""Option B: per-bot MSAL cache + concurrency-safe atomic writes.

Regression for the 2026-06 incident: one shared `.token_cache.json` written by
many scheduler threads with a SHARED tmp name + no lock → "Extra data" JSON
corruption → all bots down + new-bot setup blocked. These tests need no real
OAuth — they exercise the file-level write safety + the per-bot split/migrate.
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

# Force DATA_DIR to a temp dir BEFORE importing the app (auth.CACHE_FILE is
# derived from it at import). Dummy creds satisfy auth.py's fail-fast env check;
# the tests make no network calls.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ceo_cache_test_")
os.environ.setdefault("PROD_CLIENT_ID", "test-cid")
os.environ.setdefault("PROD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("TENANT_ID", "test-tenant")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-the-dev-default")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import storage, auth  # noqa: E402


# ── concurrency-safe atomic write ────────────────────────────────────────────

def test_atomic_write_no_corruption_under_concurrency(tmp_path):
    target = tmp_path / "race.json"

    def writer(i):
        for _ in range(20):
            storage.atomic_write_json(target, {"writer": i, "pad": "x" * (i % 9)})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(target.read_text())   # must ALWAYS parse — never "Extra data"
    assert "writer" in data
    assert not list(tmp_path.glob("*.tmp"))  # no leftover unique tmp files


# ── per-bot cache split / migrate / fallback ─────────────────────────────────

def _global_cache() -> dict:
    return {
        "Account": {
            "acctA": {"home_account_id": "bota-uid.tenant", "username": "A@x.com"},
            "acctB": {"home_account_id": "botb-uid.tenant", "username": "B@x.com"},
        },
        "RefreshToken": {
            "rtA": {"home_account_id": "bota-uid.tenant", "secret": "RT_A"},
            "rtB": {"home_account_id": "botb-uid.tenant", "secret": "RT_B"},
        },
        "AppMetadata": {"appmeta-x": {"client_id": "cid"}},  # no home_account_id → shared
    }


def _write_global(cache_dict):
    auth.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    auth.CACHE_FILE.write_text(json.dumps(cache_dict))


def test_migrate_extracts_only_that_bot():
    _write_global(_global_cache())
    out = auth._migrate_global_to_bot("bota-uid")
    assert out is not None
    o = json.loads(out)
    assert set(o["Account"]) == {"acctA"}        # only A's account
    assert set(o["RefreshToken"]) == {"rtA"}     # only A's RT
    assert "appmeta-x" in o["AppMetadata"]       # shared metadata kept
    assert "RT_B" not in out                     # B's secret never leaks


def test_migrate_returns_none_for_unknown_bot():
    _write_global(_global_cache())
    assert auth._migrate_global_to_bot("nobody-uid") is None


def test_load_cache_lazy_migrates_then_reuses_perbot_file():
    _write_global(_global_cache())
    bf = auth._bot_cache_file("bota-uid")
    if bf.exists():
        bf.unlink()

    auth._load_cache("bota-uid")                 # triggers lazy migration
    assert bf.exists()
    perbot_text = bf.read_text()
    assert set(json.loads(perbot_text)["Account"]) == {"acctA"}
    assert "RT_B" not in perbot_text             # B never lands in A's file
    # global cache left intact (still the frozen fallback / rollback source)
    assert "acctB" in json.loads(auth.CACHE_FILE.read_text())["Account"]


def test_save_cache_writes_perbot_not_global():
    _write_global(_global_cache())
    global_before = auth.CACHE_FILE.read_text()

    cache = auth.msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"Account": {"x": {"home_account_id": "z.t"}}}))
    cache.has_state_changed = True               # force a write
    auth._save_cache(cache, "newbot-uid")

    assert auth._bot_cache_file("newbot-uid").exists()
    assert auth.CACHE_FILE.read_text() == global_before  # global NOT touched


def test_refresh_success_saves_to_perbot_not_global(monkeypatch):
    """The success branch (locally un-demoable with a real token because the
    only local bot's grant is revoked): on a successful MSAL silent refresh,
    get_valid_access_token must persist the rotated cache to THIS bot's file."""
    from datetime import datetime, timedelta, timezone
    uid = "botx-uid"
    # Expired session + no web refresh_token → forces Path 2 (per-bot MSAL cache).
    auth.save_user_tokens(uid, {
        "username":      "bot@x.com",
        "access_token":  "old",
        "refresh_token": "",
        "expiry":        (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    })

    class _FakeApp:
        def get_accounts(self):
            return [{"username": "bot@x.com", "home_account_id": "botx.t"}]
        def acquire_token_silent_with_error(self, scopes, account=None):
            return {"access_token": "FAKE_TOKEN", "expires_in": 3600}

    monkeypatch.setattr(auth, "_build_legacy_app", lambda cache: _FakeApp())
    saved = {}
    monkeypatch.setattr(auth, "_save_cache", lambda c, bot_uid=None: saved.setdefault("bot_uid", bot_uid))

    tok = auth.get_valid_access_token(uid)
    assert tok == "FAKE_TOKEN"
    assert saved["bot_uid"] == uid          # rotated cache saved to per-bot file, not global
