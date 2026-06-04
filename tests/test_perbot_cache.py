"""Option B: per-bot MSAL cache + concurrency-safe writes, migrate-by-EMAIL,
and try-all-identities.

Regressions covered:
  * 2026-06 cache corruption: one shared .token_cache.json written by many
    threads with a shared tmp name + no lock.
  * 2026-06 dual-identity incident: a bot's MSAL home_account_id is NOT always
    its uid (personal/MSA accounts use opaque ids), and one email can map to
    several identities (work + personal). Migration must match by EMAIL, and
    refresh must try EACH identity (not blindly the first).

No real OAuth — file-level + mocked MSAL.
"""
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ceo_cache_test_")
os.environ.setdefault("PROD_CLIENT_ID", "test-cid")
os.environ.setdefault("PROD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("TENANT_ID", "test-tenant")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-the-dev-default")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import storage, auth  # noqa: E402


def _session(uid, email):
    auth.save_user_tokens(uid, {
        "username": email, "access_token": "old", "refresh_token": "",
        "expiry": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    })


def _write_global(cache: dict):
    auth.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    auth.CACHE_FILE.write_text(json.dumps(cache))


def _acct(email, hid):
    return {"username": email, "home_account_id": hid}


def _rt(hid, secret):
    return {"home_account_id": hid, "secret": secret}


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
    assert "writer" in json.loads(target.read_text())   # always parseable
    assert not list(tmp_path.glob("*.tmp"))


# ── migration by EMAIL — the three real account types ────────────────────────

def test_migrate_work_account_by_email():
    _session("workbot", "edileen@x.com")
    _write_global({
        "Account": {"a": _acct("edileen@x.com", "workbot.tenant"),
                    "b": _acct("other@x.com", "other.tenant")},
        "RefreshToken": {"r1": _rt("workbot.tenant", "RT1"),
                         "r2": _rt("other.tenant", "RT_OTHER")},
        "AppMetadata": {"meta": {"client_id": "cid"}},
    })
    out = json.loads(auth._migrate_global_to_bot("workbot"))
    assert set(out["Account"]) == {"a"}          # only this bot's email
    assert "meta" in out["AppMetadata"]          # shared kept
    assert "RT_OTHER" not in json.dumps(out)     # the other email excluded


def test_migrate_personal_msa_account_by_email():
    # THE 2026-06 REGRESSION: home_account_id is opaque, does NOT start with uid.
    _session("d984796b", "audrey@imodel3d.com")
    _write_global({
        "Account": {"a": _acct("audrey@imodel3d.com", "Til78opaqueMSAid")},
        "RefreshToken": {"r": _rt("Til78opaqueMSAid", "RT_MSA")},
    })
    out = auth._migrate_global_to_bot("d984796b")
    assert out is not None                        # found by EMAIL despite id mismatch
    o = json.loads(out)
    assert set(o["Account"]) == {"a"}
    assert "RT_MSA" in out                        # the working RT is included


def test_migrate_dual_identity_includes_both():
    _session("c3030d72", "audrey@ipsconsultancy.ca")
    _write_global({
        "Account": {"work": _acct("audrey@ipsconsultancy.ca", "c3030d72.tenant"),
                    "msa":  _acct("audrey@ipsconsultancy.ca", "axFm9Sopaque")},
        "RefreshToken": {"rw": _rt("c3030d72.tenant", "RT_work_stale"),
                         "rm": _rt("axFm9Sopaque", "RT_msa_valid")},
    })
    o = json.loads(auth._migrate_global_to_bot("c3030d72"))
    assert set(o["Account"]) == {"work", "msa"}   # BOTH identities for the email
    body = json.dumps(o)
    assert "RT_work_stale" in body and "RT_msa_valid" in body


def test_migrate_none_when_email_absent():
    _session("ghostbot", "ghost@x.com")
    _write_global({"Account": {"a": _acct("someone@x.com", "x.t")}})
    assert auth._migrate_global_to_bot("ghostbot") is None


# ── per-bot save isolation ───────────────────────────────────────────────────

def test_save_cache_writes_perbot_not_global():
    _write_global({"Account": {"x": _acct("a@x.com", "z.t")}})
    global_before = auth.CACHE_FILE.read_text()
    cache = auth.msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"Account": {"x": _acct("a@x.com", "z.t")}}))
    cache.has_state_changed = True
    auth._save_cache(cache, "newbot-uid")
    assert auth._bot_cache_file("newbot-uid").exists()
    assert auth.CACHE_FILE.read_text() == global_before   # global untouched


# ── try-ALL identities on refresh ────────────────────────────────────────────

def test_refresh_tries_all_identities_and_uses_the_valid_one(monkeypatch):
    """Stale identity first, valid identity second → must use the valid one
    (the 2026-06 fix: don't blindly trust matches[0])."""
    _session("dualbot", "audrey@x.com")

    class _FakeApp:
        def get_accounts(self):
            return [{"username": "audrey@x.com", "home_account_id": "stale"},
                    {"username": "audrey@x.com", "home_account_id": "valid"}]

        def acquire_token_silent_with_error(self, scopes, account=None):
            if account["home_account_id"] == "valid":
                return {"access_token": "FRESH_TOKEN", "expires_in": 3600}
            return {"error": "invalid_grant", "error_description": "AADSTS50173 revoked"}

    monkeypatch.setattr(auth, "_build_legacy_app", lambda cache: _FakeApp())
    monkeypatch.setattr(auth, "_load_cache", lambda bot_uid=None: auth.msal.SerializableTokenCache())
    monkeypatch.setattr(auth, "_save_cache", lambda c, bot_uid=None: None)

    tok = auth.get_valid_access_token("dualbot")
    assert tok == "FRESH_TOKEN"    # tried stale (failed) → valid (succeeded)


def test_refresh_success_saves_to_perbot(monkeypatch):
    _session("solobot", "solo@x.com")

    class _FakeApp:
        def get_accounts(self):
            return [{"username": "solo@x.com", "home_account_id": "h1"}]

        def acquire_token_silent_with_error(self, scopes, account=None):
            return {"access_token": "TOK", "expires_in": 3600}

    monkeypatch.setattr(auth, "_build_legacy_app", lambda cache: _FakeApp())
    monkeypatch.setattr(auth, "_load_cache", lambda bot_uid=None: auth.msal.SerializableTokenCache())
    saved = {}
    monkeypatch.setattr(auth, "_save_cache", lambda c, bot_uid=None: saved.setdefault("bot_uid", bot_uid))

    assert auth.get_valid_access_token("solobot") == "TOK"
    assert saved["bot_uid"] == "solobot"   # saved to the bot's own cache
