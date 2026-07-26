"""Auth circuit-breaker + recursion-break + log-cap regression guards.

These lock down the fix for the Max Wu runaway (2M+ token refreshes on a deleted account,
682MB×2 diag logs, container never sleeps → Railway cost spike). The core invariants:
a broken account is NOT re-probed every call, the owner↔bot notify recursion cannot spin,
the notifier can't append a dead-letter line every cycle, and no diag log can balloon."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_authq_"))
os.environ.setdefault("APP_URL", "https://example.test")
os.environ.setdefault("REDIRECT_URI", "https://example.test/auth/callback")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import auth  # noqa: E402


def _fresh_uid(tmp_path, monkeypatch, status="broken", last_attempt=None, expired=True):
    """Point auth at an isolated DATA_DIR and seed a user with a stale token + health."""
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    uid = "u-broken"
    (tmp_path / "_sessions").mkdir(parents=True, exist_ok=True)
    (tmp_path / uid).mkdir(parents=True, exist_ok=True)
    exp = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=2))
    auth.save_user_tokens(uid, {"access_token": "old", "refresh_token": "rt",
                                "expiry": exp.isoformat(), "username": "u@x.com"})
    h = auth._load_health(uid)
    h["status"] = status
    h["consecutive_failures"] = 9
    if last_attempt is not None:
        h["last_refresh_attempt_at"] = last_attempt
    auth._save_health(uid, h)
    return uid


# ── circuit breaker ──────────────────────────────────────────────────────────
def test_broken_within_backoff_fastfails_without_msal(tmp_path, monkeypatch):
    just_now = datetime.now(timezone.utc).isoformat()
    uid = _fresh_uid(tmp_path, monkeypatch, last_attempt=just_now)
    calls = {"n": 0}
    monkeypatch.setattr(auth, "_web_app", lambda: (_ for _ in ()).throw(AssertionError("MSAL called!")))
    diag_before = auth._diag_log_path(uid)
    size_before = diag_before.stat().st_size if diag_before.exists() else 0

    import pytest
    with pytest.raises(auth.AuthQuarantinedError):
        auth.get_valid_access_token(uid)

    size_after = diag_before.stat().st_size if diag_before.exists() else 0
    assert size_after == size_before   # no diag line written while quarantined


def test_broken_past_backoff_reprobes_once(tmp_path, monkeypatch):
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    uid = _fresh_uid(tmp_path, monkeypatch, last_attempt=stale)
    probed = {"n": 0}

    class _App:
        def acquire_token_by_refresh_token(self, *a, **k):
            probed["n"] += 1
            return {"error": "invalid_grant", "error_description": "AADSTS700082 expired"}
    monkeypatch.setattr(auth, "_web_app", lambda: _App())

    import pytest
    with pytest.raises(Exception):
        auth.get_valid_access_token(uid)
    assert probed["n"] == 1                                  # exactly one re-probe
    # stamp advanced → now within backoff → next call is quarantined (no probe)
    with pytest.raises(auth.AuthQuarantinedError):
        auth.get_valid_access_token(uid)
    assert probed["n"] == 1


def test_is_quarantined(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    uid = _fresh_uid(tmp_path, monkeypatch, last_attempt=now)
    assert auth.is_quarantined(uid) is True
    # healthy account is never quarantined
    h = auth._load_health(uid); h["status"] = "healthy"; auth._save_health(uid, h)
    assert auth.is_quarantined(uid) is False


def test_recovery_clears_quarantine_stamp(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    uid = _fresh_uid(tmp_path, monkeypatch, last_attempt=now)
    assert auth.is_quarantined(uid)
    auth._record_auth_success(uid, op="login")               # e.g. interactive re-login
    assert auth.is_quarantined(uid) is False
    assert auth._load_health(uid)["status"] == "healthy"


# ── log cap ──────────────────────────────────────────────────────────────────
def test_capped_append_truncates(tmp_path):
    p = tmp_path / "x.log"
    p.write_text("old\n" * 500_000)                          # ~2MB+
    big_before = p.stat().st_size
    auth._capped_append(p, "NEW LINE", cap_bytes=1024, keep_lines=10)
    assert p.stat().st_size < big_before
    lines = p.read_text().splitlines()
    assert lines[-1] == "NEW LINE" and len(lines) <= 11      # ring-buffered to the tail


# ── notifier recursion break + dead-letter backoff ──────────────────────────
def test_pick_sender_skips_broken_partner(tmp_path, monkeypatch):
    from src import auth_notifier as an
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    (tmp_path / "_sessions").mkdir(parents=True, exist_ok=True)
    # broken owner + a bot it owns that is ALSO broken → sender pick must not probe it
    owner, bot = "owner", "bot"
    for u in (owner, bot):
        (tmp_path / u).mkdir(exist_ok=True)
        auth.save_user_tokens(u, {"access_token": "x", "refresh_token": "r",
                                  "expiry": datetime.now(timezone.utc).isoformat(), "username": f"{u}@x"})
    (tmp_path / bot / "teams_bot.json").write_text(
        '{"is_registered_bot": true, "owner_uid": "owner", "enabled": true}')
    for u in (owner, bot):
        h = auth._load_health(u); h["status"] = "broken"; auth._save_health(u, h)
    monkeypatch.setattr(auth, "get_valid_access_token",
                        lambda uid: (_ for _ in ()).throw(AssertionError(f"probed broken {uid}")))
    assert an._pick_sender_uid(owner) is None                # skipped broken bot, no probe → no raise


def test_check_and_notify_reentrancy_guard(tmp_path, monkeypatch):
    from src import auth_notifier as an
    an._notifying.active = True                              # simulate "already notifying"
    try:
        # must return immediately without touching health/graph
        an.check_and_notify("anyone")
    finally:
        an._notifying.active = False


def test_deadletter_backoff_stops_reentry(tmp_path, monkeypatch):
    from src import auth_notifier as an
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    (tmp_path / "_sessions").mkdir(parents=True, exist_ok=True)
    uid = "solo"
    (tmp_path / uid).mkdir(exist_ok=True)
    auth.save_user_tokens(uid, {"access_token": "x", "refresh_token": "r",
                                "expiry": datetime.now(timezone.utc).isoformat(), "username": "s@x"})
    h = auth._load_health(uid); h["status"] = "broken"
    h["last_error"] = {"code": 700082, "description": "expired"}; auth._save_health(uid, h)
    # no recipient/sender resolvable → dead-letter path
    monkeypatch.setattr(an, "_recipient_email", lambda u: "s@x")
    monkeypatch.setattr(an, "_pick_sender_uid", lambda u: None)
    dl = an._dead_letter_path(uid)

    an.check_and_notify(uid)
    n1 = len(dl.read_text().splitlines()) if dl.exists() else 0
    an.check_and_notify(uid)                                 # immediate re-entry
    n2 = len(dl.read_text().splitlines()) if dl.exists() else 0
    assert n1 == 1 and n2 == 1                               # backoff blocked the 2nd line
