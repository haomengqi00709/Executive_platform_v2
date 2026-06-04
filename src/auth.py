"""
Auth module — two modes:
  - Web OAuth (Authorization Code Flow) for deployed multi-user use
  - Device Code Flow for local CLI development

Sessions: JWT cookie (stateless, survives restarts)
Tokens:   stored per-user in DATA_DIR/sessions/{user_id}.json
"""
import json
import msal
import os
import secrets
import jwt as pyjwt
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

from src.storage import atomic_write_text, file_lock

load_dotenv()

# ── Config ────────────────────────────────────────────────
# Fail-fast pattern: production-critical env vars must be explicitly set.
# Defaults only kept for things that have a safe local-dev meaning.

def _required_env(name: str) -> str:
    """Return env var value or raise with a clear message."""
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"{name} env var must be set. "
            f"See .env.example for the full list of required variables."
        )
    return v

PROD_CLIENT_ID     = _required_env("PROD_CLIENT_ID")
PROD_CLIENT_SECRET = _required_env("PROD_CLIENT_SECRET")
TENANT_ID          = _required_env("TENANT_ID")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET or SESSION_SECRET == "dev-secret-change-in-prod":
    raise RuntimeError(
        "SESSION_SECRET must be set to a random secret (not the dev default). "
        "Generate one: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )

# CLIENT_ID is used for device-flow (local dev / bot registration).
# Keep a default for convenience but warn loudly so prod deploys notice.
CLIENT_ID = os.getenv("CLIENT_ID")
if not CLIENT_ID:
    CLIENT_ID = "e6e14f41-4c7b-4c0d-b181-6710bd1c6444"
    print("[Auth WARNING] CLIENT_ID not set — using dev default. Set explicitly in production.")

# REDIRECT_URI defaults to localhost so local dev "just works".
# Web OAuth derives the callback URL from request headers at runtime
# (src/server.py:_detect_redirect_uri), so this default rarely matters in deployed environments.
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent / ".data")))

AUTHORITY_COMMON = "https://login.microsoftonline.com/common"
AUTHORITY_LEGACY = f"https://login.microsoftonline.com/{TENANT_ID}"

SCOPES_WEB = [
    "Mail.Read", "Mail.ReadWrite", "Mail.Send",
    "Calendars.Read", "Calendars.ReadWrite",
    "Files.Read", "Files.Read.All", "Files.ReadWrite",
    "Sites.Read.All",
    "User.Read",
    "Tasks.ReadWrite",
    "Chat.ReadWrite",
    "MailboxSettings.Read",
]
SCOPES_LOCAL = [
    "Mail.Read", "Mail.ReadWrite", "Mail.Send",
    "Calendars.Read", "Calendars.ReadWrite",
    "User.Read", "Contacts.Read",
    "Files.Read", "Files.ReadWrite",
    "Sites.Read.All",
    "Tasks.ReadWrite",
    "Chat.ReadWrite",
]

CACHE_FILE = DATA_DIR / ".token_cache.json"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

# ── User data paths ───────────────────────────────────────

def user_data_dir(user_id: str) -> Path:
    d = DATA_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def _sessions_dir() -> Path:
    d = DATA_DIR / "_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _token_file(user_id: str) -> Path:
    return _sessions_dir() / f"{user_id}.json"


# ── Token storage (MS access/refresh tokens) ─────────────

def save_user_tokens(user_id: str, token_data: dict):
    # Atomic write: temp + rename. Plain write_text() over Azure Files SMB can
    # leave stale trailing bytes on partial writes (seen in production:
    # 4929-byte file = 4928 valid JSON + 1 stray "}" -> json.loads raises
    # "Extra data" -> get_valid_access_token thinks token is missing -> all
    # background pollers fail with "No token found for user").
    atomic_write_text(_token_file(user_id), json.dumps(token_data, default=str))

def load_user_tokens(user_id: str) -> dict | None:
    f = _token_file(user_id)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return None

def delete_user_tokens(user_id: str):
    f = _token_file(user_id)
    if f.exists():
        f.unlink()


# ── JWT session cookie ────────────────────────────────────

def create_jwt(user_id: str, username: str) -> str:
    payload = {
        "user_id":  user_id,
        "username": username,
        "exp":      datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat":      datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, SESSION_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token: str) -> dict | None:
    try:
        return pyjwt.decode(token, SESSION_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


# ── Web OAuth (Authorization Code Flow) ───────────────────

def _web_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        PROD_CLIENT_ID,
        authority=AUTHORITY_COMMON,
        client_credential=PROD_CLIENT_SECRET,
    )

def get_auth_url(state: str, redirect_uri: str = None) -> str:
    return _web_app().get_authorization_request_url(
        SCOPES_WEB,
        state=state,
        redirect_uri=redirect_uri or REDIRECT_URI,
        prompt="select_account",
    )

def exchange_code(code: str, redirect_uri: str = None) -> dict:
    result = _web_app().acquire_token_by_authorization_code(
        code, scopes=SCOPES_WEB, redirect_uri=redirect_uri or REDIRECT_URI,
    )
    if "error" in result:
        raise Exception(result.get("error_description", "Auth failed"))
    return result

def get_valid_access_token(user_id: str) -> str:
    """Get a valid MS access token for user, refreshing if needed.
    Tries web-app refresh first; falls back to MSAL cache for device-flow accounts."""
    data = load_user_tokens(user_id)
    if not data:
        raise Exception("No token found for user")

    expiry = datetime.fromisoformat(data["expiry"])
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) < expiry - timedelta(minutes=5):
        return data["access_token"]

    last_msal_error: dict | None = None

    # Try web-app refresh (works for OAuth web-login users)
    if data.get("refresh_token"):
        try:
            result = _web_app().acquire_token_by_refresh_token(
                data["refresh_token"], scopes=SCOPES_WEB,
            )
            if "error" not in result:
                new_data = {
                    "access_token":  result["access_token"],
                    "refresh_token": result.get("refresh_token", data["refresh_token"]),
                    "expiry":        (datetime.now(timezone.utc) + timedelta(seconds=result.get("expires_in", 3600))).isoformat(),
                    "username":      data.get("username", ""),
                }
                save_user_tokens(user_id, new_data)
                _record_auth_success(user_id, op="refresh")
                return new_data["access_token"]
            else:
                last_msal_error = result
        except Exception as e:
            last_msal_error = {"error": "exception", "error_description": str(e)}

    # Fall back to the per-bot MSAL cache (device-flow accounts like the bot).
    # Hold the per-bot lock around the whole load→silent-refresh→save so two
    # concurrent polls for the same bot can't race the refresh-token rotation.
    username = data.get("username", "")
    if username:
        with file_lock(_bot_cache_file(user_id)):
            cache   = _load_cache(user_id)
            app     = _build_legacy_app(cache)
            matches = [a for a in app.get_accounts() if a.get("username", "").lower() == username.lower()]
            if matches:
                try:
                    result = app.acquire_token_silent_with_error(SCOPES_LOCAL, account=matches[0])
                except Exception as e:
                    result = {"error": "exception", "error_description": str(e)}
                if result and "access_token" in result:
                    _save_cache(cache, user_id)
                    new_data = {
                        "access_token":  result["access_token"],
                        "refresh_token": "",
                        "expiry":        (datetime.now(timezone.utc) + timedelta(seconds=result.get("expires_in", 3600))).isoformat(),
                        "username":      username,
                    }
                    save_user_tokens(user_id, new_data)
                    _record_auth_success(user_id, op="silent")
                    return new_data["access_token"]
                if result and "error" in result:
                    last_msal_error = result

    _record_auth_failure(user_id, last_msal_error)
    raise Exception(f"Could not refresh token for {user_id}")


# ── Health state + diagnostic logging ─────────────────────
# Persists per-user auth health so the frontend can show a status indicator
# and the notifier can detect healthy→broken transitions. Every refresh attempt
# also writes one line to .data/{user_id}/.auth_diag.log for after-the-fact
# debugging. Per-user files (not a global file) so we can pull one customer's
# history in isolation via /api/admin/diag/{user_id}.

_BROKEN_THRESHOLD = 4  # consecutive failures before status flips to "broken"

def _health_path(user_id: str) -> Path:
    return user_data_dir(user_id) / ".auth_health.json"


def _diag_log_path(user_id: str) -> Path:
    return user_data_dir(user_id) / ".auth_diag.log"


def _load_health(user_id: str) -> dict:
    p = _health_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"status": "healthy", "consecutive_failures": 0, "last_success_at": None,
            "last_failure_at": None, "last_error": None, "broken_since": None}


def _save_health(user_id: str, health: dict):
    p = _health_path(user_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(health, indent=2))
    os.replace(tmp, p)


def _append_diag_log(user_id: str, line: str):
    try:
        path = _diag_log_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _record_auth_success(user_id: str, op: str):
    now = datetime.now(timezone.utc).isoformat()
    health = _load_health(user_id)
    was_broken = health.get("status") == "broken"
    health.update({
        "status": "healthy",
        "consecutive_failures": 0,
        "last_success_at": now,
        "broken_since": None,
    })
    # On recovery, clear the notification history so the NEXT break gets a
    # fresh "first" email, not a stale "skip" from the previous broken cycle.
    # Without this, after a break-recover-break sequence the user would never
    # hear about the second break (sent_count stays at 1, _should_send skips).
    if was_broken:
        health["notifications"] = {}
    _save_health(user_id, health)
    _append_diag_log(user_id, f"{now}  op={op}  result=OK")
    if was_broken:
        _append_diag_log(user_id, f"{now}  event=RECOVERED")


def _record_auth_failure(user_id: str, msal_error: dict | None):
    from src.auth_errors import extract_aadsts_code
    now = datetime.now(timezone.utc).isoformat()
    code, desc = extract_aadsts_code(msal_error)
    health = _load_health(user_id)
    health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
    health["last_failure_at"] = now
    health["last_error"] = {
        "code": code,
        "msal_error": (msal_error or {}).get("error"),
        "description": desc[:500],
        "correlation_id": (msal_error or {}).get("correlation_id"),
    }
    just_broke = False
    if health["consecutive_failures"] >= _BROKEN_THRESHOLD and health.get("status") != "broken":
        health["status"] = "broken"
        health["broken_since"] = now
        just_broke = True
    _save_health(user_id, health)

    corr = (msal_error or {}).get("correlation_id", "")
    msg_short = (desc or "").replace("\n", " ")[:200]
    _append_diag_log(
        user_id,
        f"{now}  op=refresh  result=FAIL  "
        f"aadsts={code}  consecutive={health['consecutive_failures']}  "
        f"corr={corr}  msg=\"{msg_short}\"",
    )
    if just_broke:
        _append_diag_log(user_id, f"{now}  event=BROKEN  aadsts={code}")

    if health.get("status") == "broken":
        try:
            from src.auth_notifier import check_and_notify
            check_and_notify(user_id)
        except Exception as e:
            _append_diag_log(user_id, f"{now}  event=NOTIFY_ERROR  err={e!r}")


def get_auth_health(user_id: str) -> dict:
    """Returns the persisted health record for a user_id (or a default if none exists).
    Frontend / notifier use this to show status and decide whether to alert."""
    return _load_health(user_id)


# ── Legacy Device Code Flow (local dev) ───────────────────

def _bot_cache_file(bot_uid: str) -> Path:
    """Per-bot MSAL cache. Replaces the single shared global cache so one bot's
    token churn/corruption can't affect another (the 2026-06 incident)."""
    return user_data_dir(bot_uid) / "msal_cache.json"


def _migrate_global_to_bot(bot_uid: str) -> str | None:
    """Best-effort: pull this bot's entries out of the legacy global cache and
    return them serialized, to seed the per-bot cache on first read. Filters
    every cache category by home_account_id prefix == bot_uid; keeps entries
    with no home_account_id (e.g. AppMetadata — shared, harmless). Returns None
    if the global cache holds nothing for this bot."""
    if not CACHE_FILE.exists():
        return None
    raw = CACHE_FILE.read_text()
    try:
        full = json.loads(raw)
    except Exception:
        try:                                   # salvage a corrupted global cache
            full, _ = json.JSONDecoder().raw_decode(raw)
        except Exception:
            return None
    if not isinstance(full, dict):
        return None
    out: dict = {}
    found = False
    for category, entries in full.items():
        if not isinstance(entries, dict):
            out[category] = entries
            continue
        kept = {}
        for k, v in entries.items():
            hid = (v.get("home_account_id") or "") if isinstance(v, dict) else ""
            if (not hid) or hid.lower().startswith(bot_uid.lower()):
                kept[k] = v
                if hid:
                    found = True
        if kept:
            out[category] = kept
    return json.dumps(out) if found else None


def _load_cache(bot_uid: str | None = None) -> msal.SerializableTokenCache:
    """Load the MSAL cache. With bot_uid → that bot's own file, lazily seeded
    from the legacy global cache on first read, falling back to the global
    cache if needed (so a bot always finds its token). Without bot_uid → the
    legacy global cache (local dev / owner device flow)."""
    cache = msal.SerializableTokenCache()
    if bot_uid:
        bf = _bot_cache_file(bot_uid)
        if bf.exists():                         # 1. per-bot file
            try:
                cache.deserialize(bf.read_text())
                return cache
            except Exception:
                cache = msal.SerializableTokenCache()
        migrated = _migrate_global_to_bot(bot_uid)   # 2. lazy migrate from global
        if migrated:
            try:
                cache.deserialize(migrated)
                atomic_write_text(bf, migrated)
                print(f"[cache] migrated per-bot cache for {bot_uid}")
                return cache
            except Exception as e:
                print(f"[cache] per-bot migrate failed for {bot_uid}: {e}")
                cache = msal.SerializableTokenCache()
        # 3. fall through to the legacy global cache so the bot still works
    if CACHE_FILE.exists():
        try:
            cache.deserialize(CACHE_FILE.read_text())
        except Exception:
            pass
    return cache


def _save_cache(cache: msal.SerializableTokenCache, bot_uid: str | None = None):
    """Persist the cache. With bot_uid → the bot's own file (never the shared
    global one, which is now a frozen fallback). Concurrency-safe write."""
    if not cache.has_state_changed:
        return
    target = _bot_cache_file(bot_uid) if bot_uid else CACHE_FILE
    atomic_write_text(target, cache.serialize())

def _build_legacy_app(cache) -> msal.PublicClientApplication:
    # Use /common authority so multi-tenant users (e.g. Audrey@<their-domain>)
    # can register as bot accounts via device flow. The Azure app registration
    # must also be set to multi-tenant in Azure portal; both must agree, else
    # AADSTS50020 fires.
    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY_COMMON, token_cache=cache)

def get_token() -> str:
    cache = _load_cache()
    app   = _build_legacy_app(cache)
    account = next(iter(app.get_accounts()), None)
    if account:
        result = app.acquire_token_silent(SCOPES_LOCAL, account=account)
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]
    raise Exception("Not authenticated. Run device code flow first.")

def start_device_flow() -> dict:
    cache = _load_cache()
    app   = _build_legacy_app(cache)
    flow  = app.initiate_device_flow(scopes=SCOPES_LOCAL)
    if "error" in flow:
        raise Exception(flow.get("error_description", "Device flow error"))
    return flow

def complete_device_flow(flow: dict) -> str:
    cache  = _load_cache()
    app    = _build_legacy_app(cache)
    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)
    if "access_token" in result:
        return result["access_token"]
    raise Exception(result.get("error_description", "Auth failed"))

def is_authenticated() -> bool:
    try:
        get_token()
        return True
    except Exception:
        return False

def get_signed_in_user() -> str | None:
    cache = _load_cache()
    app   = _build_legacy_app(cache)
    accounts = app.get_accounts()
    return accounts[0].get("username") if accounts else None
