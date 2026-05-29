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

load_dotenv()

# ── Config ────────────────────────────────────────────────
CLIENT_ID          = os.getenv("CLIENT_ID",          "e6e14f41-4c7b-4c0d-b181-6710bd1c6444")
TENANT_ID          = os.getenv("TENANT_ID",          "08d3a3f1-0366-451e-98ce-74626f1bf75f")
PROD_CLIENT_ID     = os.getenv("PROD_CLIENT_ID",     "6e538eee-e90b-4432-bb14-329d5d70d623")
PROD_CLIENT_SECRET = os.getenv("PROD_CLIENT_SECRET", "")
REDIRECT_URI       = os.getenv("REDIRECT_URI",       "http://localhost:8000/auth/callback")
SESSION_SECRET     = os.getenv("SESSION_SECRET",     "dev-secret-change-in-prod")
DATA_DIR           = Path(os.getenv("DATA_DIR",      str(Path(__file__).parent.parent / ".data")))

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

# On startup: if AUDREY_TOKEN_CACHE env var is set and file doesn't exist, write it
def _seed_token_cache():
    import base64
    encoded = os.getenv("AUDREY_TOKEN_CACHE", "")
    if encoded and not CACHE_FILE.exists():
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(base64.b64decode(encoded).decode())
            print(f"[Auth] Seeded Audrey token cache from env var → {CACHE_FILE}")
        except Exception as e:
            print(f"[Auth] Failed to seed token cache: {e}")

_seed_token_cache()


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
    _token_file(user_id).write_text(json.dumps(token_data, default=str))

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

    # Fall back to MSAL cache (works for device-flow accounts like the bot)
    username = data.get("username", "")
    if username:
        cache   = _load_cache()
        app     = _build_legacy_app(cache)
        matches = [a for a in app.get_accounts() if a.get("username", "").lower() == username.lower()]
        if matches:
            try:
                result = app.acquire_token_silent_with_error(SCOPES_LOCAL, account=matches[0])
            except Exception as e:
                result = {"error": "exception", "error_description": str(e)}
            if result and "access_token" in result:
                _save_cache(cache)
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
# also writes one line to .data/.auth_diag.log for after-the-fact debugging.

_DIAG_LOG = DATA_DIR / ".auth_diag.log"
_BROKEN_THRESHOLD = 4  # consecutive failures before status flips to "broken"

def _health_path(user_id: str) -> Path:
    return user_data_dir(user_id) / ".auth_health.json"


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


def _append_diag_log(line: str):
    try:
        _DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_DIAG_LOG, "a") as f:
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
    _append_diag_log(f"{now}  user={user_id}  op={op}  result=OK")
    if was_broken:
        _append_diag_log(f"{now}  user={user_id}  event=RECOVERED")


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
        f"{now}  user={user_id}  op=refresh  result=FAIL  "
        f"aadsts={code}  consecutive={health['consecutive_failures']}  "
        f"corr={corr}  msg=\"{msg_short}\""
    )
    if just_broke:
        _append_diag_log(f"{now}  user={user_id}  event=BROKEN  aadsts={code}")

    if health.get("status") == "broken":
        try:
            from src.auth_notifier import check_and_notify
            check_and_notify(user_id)
        except Exception as e:
            _append_diag_log(f"{now}  user={user_id}  event=NOTIFY_ERROR  err={e!r}")


def get_auth_health(user_id: str) -> dict:
    """Returns the persisted health record for a user_id (or a default if none exists).
    Frontend / notifier use this to show status and decide whether to alert."""
    return _load_health(user_id)


# ── Legacy Device Code Flow (local dev) ───────────────────

def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    return cache

def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        import os, tempfile
        data = cache.serialize()
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(data)
        os.replace(tmp, CACHE_FILE)  # atomic on POSIX — prevents partial-write corruption

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
