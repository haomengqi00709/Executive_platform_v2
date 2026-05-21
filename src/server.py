"""
Minimal FastAPI server — Auth only.
Provides:
  - Web OAuth (Authorization Code Flow): /auth/login, /auth/callback, /auth/logout
  - Device Code Flow (local dev): /api/auth/start, /api/auth/poll
  - Session helpers: /api/auth/me, /api/auth/status
  - Graph test endpoint: /api/test/graph
  - Health check: /health
"""
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv

from src import auth
from src.graph import GraphClient

load_dotenv(override=True)

app = FastAPI(title="CEO AI Platform v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Ensure .data/ directory exists on startup
Path(".data/_sessions").mkdir(parents=True, exist_ok=True)

_device_flow: dict = {}
_device_flow_lock  = threading.Lock()


# ── Session helpers ───────────────────────────────────────

def get_current_session(session_token: str = Cookie(None)) -> dict | None:
    if not session_token:
        return None
    return auth.decode_jwt(session_token)

def require_session(session: dict | None = Depends(get_current_session)) -> dict:
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


# ── Redirect URI detection ────────────────────────────────

def _detect_redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI from the actual incoming request host."""
    proto = request.headers.get("x-forwarded-proto") or ("https" if request.url.scheme == "https" else "http")
    host  = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8000"
    return f"{proto}://{host}/auth/callback"


# ── Web OAuth endpoints ───────────────────────────────────

@app.get("/auth/login")
def login(request: Request):
    state        = secrets.token_urlsafe(16)
    redirect_uri = _detect_redirect_uri(request)
    url          = auth.get_auth_url(state, redirect_uri=redirect_uri)
    resp         = RedirectResponse(url)
    resp.set_cookie("oauth_state",    state,        httponly=True, max_age=600)
    resp.set_cookie("oauth_redirect", redirect_uri, httponly=True, max_age=600)
    return resp


@app.get("/auth/callback")
def auth_callback(code: str = None, state: str = None, error: str = None,
                  oauth_state: str = Cookie(None), oauth_redirect: str = Cookie(None)):
    if error:
        return RedirectResponse(f"/?error={error}")
    if not code:
        return RedirectResponse("/?error=no_code")

    try:
        result = auth.exchange_code(code, redirect_uri=oauth_redirect)
    except Exception as e:
        return RedirectResponse(f"/?error={str(e)[:80]}")

    claims   = result.get("id_token_claims", {})
    user_id  = claims.get("oid") or claims.get("sub", "unknown")
    username = claims.get("preferred_username") or claims.get("email", "")
    expiry   = (datetime.now(timezone.utc) + timedelta(seconds=result.get("expires_in", 3600))).isoformat()

    auth.save_user_tokens(user_id, {
        "access_token":  result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "expiry":        expiry,
        "username":      username,
    })

    jwt_token = auth.create_jwt(user_id, username)
    base = oauth_redirect.rsplit("/auth/callback", 1)[0] if oauth_redirect else ""
    resp = RedirectResponse(f"{base}/")
    resp.set_cookie("session_token", jwt_token, httponly=True, secure=False, max_age=60*60*24*7, samesite="lax")
    resp.delete_cookie("oauth_state")
    resp.delete_cookie("oauth_redirect")
    return resp


@app.get("/auth/logout")
def logout(session_token: str = Cookie(None)):
    session = auth.decode_jwt(session_token) if session_token else None
    if session:
        auth.delete_user_tokens(session["user_id"])
    resp = RedirectResponse("/")
    resp.delete_cookie("session_token")
    return resp


# ── Auth info endpoints ───────────────────────────────────

@app.get("/api/auth/me")
def auth_me(session: dict | None = Depends(get_current_session)):
    if not session:
        return {"authenticated": False}
    return {"authenticated": True, "username": session.get("username"), "user_id": session.get("user_id")}


@app.get("/api/auth/status")
def auth_status():
    user = auth.get_signed_in_user() if hasattr(auth, "get_signed_in_user") else None
    return {"authenticated": auth.is_authenticated(), "user": user}


# ── Device Code Flow (local dev) ──────────────────────────

@app.post("/api/auth/start")
def auth_start():
    with _device_flow_lock:
        global _device_flow
        flow = auth.start_device_flow()
        _device_flow = flow
        return {
            "user_code":        flow["user_code"],
            "verification_uri": flow["verification_uri"],
            "message":          flow["message"],
            "expires_in":       flow.get("expires_in", 900),
        }


@app.post("/api/auth/poll")
def auth_poll(response: Response):
    with _device_flow_lock:
        if not _device_flow:
            return {"status": "no_flow"}
        try:
            token = auth.complete_device_flow(_device_flow)
            _device_flow.clear()
            cache   = auth._load_cache()
            app_    = auth._build_legacy_app(cache)
            account = next(iter(app_.get_accounts()), None)
            if account:
                import requests as _req
                me = _req.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                ).json()
                user_id  = me.get("id", account.get("local_account_id", "local"))
                username = me.get("mail") or me.get("userPrincipalName") or account.get("username", "")
                expiry   = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                auth.save_user_tokens(user_id, {
                    "access_token":  token,
                    "refresh_token": "",
                    "expiry":        expiry,
                    "username":      username,
                })
                jwt_token = auth.create_jwt(user_id, username)
                response.set_cookie("session_token", jwt_token, httponly=True,
                                    secure=False, max_age=60*60*24*7, samesite="lax")
            return {"status": "success"}
        except Exception as e:
            msg = str(e)
            if "authorization_pending" in msg or "slow_down" in msg:
                return {"status": "pending"}
            return {"status": "error", "message": msg}


# ── Graph test endpoint ───────────────────────────────────

@app.get("/api/test/graph")
def test_graph(session: dict = Depends(require_session)):
    """Verify the full auth → Graph API chain works. Returns user info + last 3 emails."""
    uid = session["user_id"]
    try:
        token = auth.get_valid_access_token(uid)
        graph = GraphClient(token)
        me    = graph.get_me()
        msgs  = graph.get_messages(top=3)
        return {
            "ok":       True,
            "user":     {
                "displayName":        me.get("displayName"),
                "mail":               me.get("mail"),
                "userPrincipalName":  me.get("userPrincipalName"),
            },
            "latest_emails": [
                {
                    "subject":  m.get("subject"),
                    "from":     m.get("from", {}).get("emailAddress", {}).get("address"),
                    "received": m.get("receivedDateTime", "")[:16],
                }
                for m in msgs
            ],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ── Health check ──────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
