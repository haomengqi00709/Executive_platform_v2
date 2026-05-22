"""
CEO AI Platform v2 — FastAPI server
Auth + Settings + Teams bot registration
"""
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler

from src import auth
from src.graph import GraphClient
from src.ai import AIClient
from src.sections import ai_summary, expenses

load_dotenv(override=True)

import os
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

app = FastAPI(title="CEO AI Platform v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

Path(".data/_sessions").mkdir(parents=True, exist_ok=True)

_device_flow: dict = {}
_device_flow_lock = threading.Lock()
_bot_device_flow: dict = {}
_bot_device_flow_lock = threading.Lock()

_scheduler = BackgroundScheduler(timezone="UTC")


# ── File helpers ──────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}

def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def _udir(user_id: str) -> Path:
    return auth.DATA_DIR / user_id

def _user_settings(user_id: str) -> Path:
    return _udir(user_id) / "settings.json"

def _user_bot_link_path(user_id: str) -> Path:
    return _udir(user_id) / "bot_link.json"


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
        return RedirectResponse(f"{FRONTEND_URL}/?error={error}")
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/?error=no_code")
    try:
        result = auth.exchange_code(code, redirect_uri=oauth_redirect)
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/?error={str(e)[:80]}")

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
    resp = RedirectResponse(f"{FRONTEND_URL}/")
    resp.set_cookie("session_token", jwt_token, httponly=True, secure=False, max_age=60*60*24*7, samesite="lax")
    resp.delete_cookie("oauth_state")
    resp.delete_cookie("oauth_redirect")
    return resp


@app.get("/auth/logout")
def logout(session_token: str = Cookie(None)):
    session = auth.decode_jwt(session_token) if session_token else None
    if session:
        auth.delete_user_tokens(session["user_id"])
    resp = RedirectResponse(f"{FRONTEND_URL}/")
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
    return {"authenticated": False}


# ── Device Code Flow (main user login) ────────────────────

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


# ── Settings ──────────────────────────────────────────────

@app.get("/api/settings")
def get_settings(request: Request, session: dict = Depends(require_session)):
    uid      = session["user_id"]
    path     = _user_settings(uid)
    settings = _read_json(path)
    if not settings.get("report_email"):
        ms_email = (auth.load_user_tokens(uid) or {}).get("username", "")
        settings.setdefault("report_email", ms_email)
    tz = request.headers.get("X-Timezone", "").strip()
    if tz and settings.get("timezone") != tz:
        settings["timezone"] = tz
        _write_json(path, settings)
    return settings


@app.patch("/api/settings")
def update_settings(body: dict, session: dict = Depends(require_session)):
    uid  = session["user_id"]
    path = _user_settings(uid)
    settings = _read_json(path)
    settings.update(body)
    _write_json(path, settings)
    return settings


# ── Bot helpers ───────────────────────────────────────────

def _bot_state_path(user_id: str) -> Path:
    return _udir(user_id) / "teams_bot.json"


def _find_bot_for_user(user_id: str):
    link_path = _user_bot_link_path(user_id)
    if link_path.exists():
        bot_uid = _read_json(link_path).get("bot_uid")
        if bot_uid:
            bp = _bot_state_path(bot_uid)
            if bp.exists():
                bs = json.loads(bp.read_text())
                if bs.get("enabled") and bs.get("owner_uid") == user_id:
                    return bot_uid, bs.get("chat_id")
            link_path.unlink(missing_ok=True)

    sessions_dir = auth.DATA_DIR / "_sessions"
    for tf in sorted(sessions_dir.glob("*.json")):
        bid = tf.stem
        if bid == user_id:
            continue
        bp = _bot_state_path(bid)
        if not bp.exists():
            continue
        bs = json.loads(bp.read_text())
        if bs.get("enabled") and bs.get("owner_uid") == user_id and bs.get("chat_id"):
            _write_json(link_path, {"bot_uid": bid})
            return bid, bs["chat_id"]

    return None, None


def _bind_bot_to_user(bot_uid: str, user_id: str, username: str):
    existing = _read_json(_user_bot_link_path(user_id)).get("bot_uid")
    if existing and existing != bot_uid:
        ep = _bot_state_path(existing)
        if ep.exists():
            es = json.loads(ep.read_text())
            es.update({"owner_uid": None, "peer_email": None, "chat_id": None, "last_seen_ts": None})
            _write_json(ep, es)

    bp = _bot_state_path(bot_uid)
    bs = json.loads(bp.read_text()) if bp.exists() else {}
    prev_owner = bs.get("owner_uid")
    if prev_owner and prev_owner != user_id:
        prev_link = _user_bot_link_path(prev_owner)
        if prev_link.exists() and _read_json(prev_link).get("bot_uid") == bot_uid:
            prev_link.unlink(missing_ok=True)

    bs.update({
        "enabled":           True,
        "is_registered_bot": True,
        "owner_uid":         user_id,
        "peer_email":        username,
        "chat_id":           None,
        "last_seen_ts":      None,
    })
    _write_json(bp, bs)
    _write_json(_user_bot_link_path(user_id), {"bot_uid": bot_uid})


def _unbind_bot_from_user(user_id: str) -> str | None:
    link_path = _user_bot_link_path(user_id)
    bot_uid = _read_json(link_path).get("bot_uid") if link_path.exists() else None
    if not bot_uid:
        sessions_dir = auth.DATA_DIR / "_sessions"
        for tf in sessions_dir.glob("*.json"):
            bid = tf.stem
            if bid == user_id:
                continue
            bp = _bot_state_path(bid)
            if not bp.exists():
                continue
            bs = json.loads(bp.read_text())
            if bs.get("enabled") and bs.get("owner_uid") == user_id:
                bot_uid = bid
                break
    if bot_uid:
        bp = _bot_state_path(bot_uid)
        if bp.exists():
            bs = json.loads(bp.read_text())
            bs.update({"owner_uid": None, "peer_email": None, "chat_id": None, "last_seen_ts": None})
            _write_json(bp, bs)
        link_path.unlink(missing_ok=True)
    return bot_uid


def _send_activation_greeting(bot_uid: str, peer_email: str, display_name: str):
    import time
    time.sleep(3)
    try:
        token   = auth.get_valid_access_token(bot_uid)
        graph   = GraphClient(token)
        chat_id = graph.find_chat_with_user(peer_email)
        if not chat_id:
            return
        bp    = _bot_state_path(bot_uid)
        state = json.loads(bp.read_text())
        state["chat_id"]      = chat_id
        state["last_seen_ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        _write_json(bp, state)

        bot_me      = graph.get_me()
        bot_display = bot_me.get("displayName") or peer_email.split("@")[0]
        greeting = (
            f"Hi {display_name}! 👋 I'm {bot_display}, your AI executive assistant.\n\n"
            f"I'm now connected. Here's what I can do:\n"
            f"• 📧 Alert you to important emails and draft replies\n"
            f"• 📅 Send pre-meeting briefs and reminders\n"
            f"• 🌅 Deliver your morning briefing each day\n"
            f"• 💬 Answer questions — just ask me anything here!"
        )
        graph.send_chat_message(chat_id, greeting)
    except Exception as e:
        print(f"[TeamsBot] Greeting failed for {peer_email}: {e}")


# ── Teams bot polling (scheduler) ─────────────────────────

def _poll_teams_bot_all_users():
    from src.modules.teams_bot import poll_and_reply
    sessions_dir = auth.DATA_DIR / "_sessions"
    if not sessions_dir.exists():
        return
    for token_file in sessions_dir.glob("*.json"):
        uid  = token_file.stem
        path = _bot_state_path(uid)
        if not path.exists():
            continue
        try:
            state = _read_json(path)
            if not state.get("enabled") or not state.get("is_registered_bot"):
                continue
            token       = auth.get_valid_access_token(uid)
            graph       = GraphClient(token)
            owner_uid   = state.get("owner_uid") or uid
            owner_settings = _read_json(_user_settings(owner_uid))
            owner_graph = None
            try:
                owner_graph = GraphClient(auth.get_valid_access_token(owner_uid))
            except Exception:
                pass
            new_state = poll_and_reply(
                state, graph, None,
                owner_graph=owner_graph,
                owner_wiki_dir=_udir(owner_uid) / "wiki",
                owner_settings=owner_settings,
                owner_settings_path=_user_settings(owner_uid),
                owner_context_path=_udir(owner_uid) / "context.json",
                owner_data_dir=_udir(owner_uid),
                bot_state_path=path,
            )
            path.write_text(json.dumps(new_state, indent=2, ensure_ascii=False))
        except Exception as e:
            msg = str(e)
            if not any(c in msg for c in ("502", "503", "504", "ConnectionError", "Timeout")):
                print(f"[TeamsBot] Error for {uid}: {e}")


# ── Teams bot API ─────────────────────────────────────────

@app.get("/api/teams/bot")
def get_bot_status(session: dict = Depends(require_session)):
    uid   = session["user_id"]
    path  = _bot_state_path(uid)
    state = json.loads(path.read_text()) if path.exists() else {}

    # Also check if a *separate* bot account is bound to this user
    bot_uid, chat_id = _find_bot_for_user(uid)
    if bot_uid:
        bp  = _bot_state_path(bot_uid)
        bs  = json.loads(bp.read_text()) if bp.exists() else {}
        bot_email = (auth.load_user_tokens(bot_uid) or {}).get("username", "")
        return {
            "enabled":      True,
            "peer_email":   bs.get("peer_email", ""),
            "bot_email":    bot_email,
            "chat_id":      chat_id,
            "last_seen_ts": bs.get("last_seen_ts"),
        }

    return {
        "enabled":      state.get("enabled", False),
        "peer_email":   state.get("peer_email", ""),
        "bot_email":    "",
        "chat_id":      state.get("chat_id"),
        "last_seen_ts": state.get("last_seen_ts"),
    }


@app.post("/api/teams/bot/auth-start")
def bot_auth_start(session: dict = Depends(require_session)):
    import concurrent.futures
    global _bot_device_flow
    with _bot_device_flow_lock:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(auth.start_device_flow)
            try:
                flow = future.result(timeout=20)
            except concurrent.futures.TimeoutError:
                raise HTTPException(504, "Timeout connecting to Microsoft — please retry")
        _bot_device_flow = flow
        return {
            "user_code":        flow["user_code"],
            "verification_url": flow["verification_uri"],
            "expires_in":       flow.get("expires_in", 900),
        }


@app.post("/api/teams/bot/auth-poll")
def bot_auth_poll(session: dict = Depends(require_session)):
    global _bot_device_flow
    with _bot_device_flow_lock:
        if not _bot_device_flow:
            return {"status": "no_flow"}
        try:
            token = auth.complete_device_flow(_bot_device_flow)
            _bot_device_flow.clear()

            import requests as _req
            me = _req.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            ).json()
            bot_uid   = me.get("id", "")
            bot_email = me.get("mail") or me.get("userPrincipalName", "")
            if bot_uid:
                expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                auth.save_user_tokens(bot_uid, {
                    "access_token":  token,
                    "refresh_token": "",
                    "expiry":        expiry,
                    "username":      bot_email,
                })
                bp = _bot_state_path(bot_uid)
                bs = json.loads(bp.read_text()) if bp.exists() else {}
                bs["enabled"]           = True
                bs["is_registered_bot"] = True
                _write_json(bp, bs)

            return {"status": "success", "bot_email": bot_email, "bot_uid": bot_uid}
        except Exception as e:
            msg = str(e)
            if "authorization_pending" in msg or "slow_down" in msg:
                return {"status": "pending"}
            return {"status": "error", "message": msg}


@app.post("/api/teams/bot/activate")
def activate_bot(background_tasks: BackgroundTasks, session: dict = Depends(require_session),
                 bot_uid: str = None):
    user_id  = session["user_id"]
    username = session["username"]
    if not bot_uid:
        raise HTTPException(400, "bot_uid is required")
    bp = _bot_state_path(bot_uid)
    if not bp.exists():
        raise HTTPException(404, "Bot account not found")
    bs = json.loads(bp.read_text())
    if not bs.get("enabled"):
        raise HTTPException(400, "Bot account is not enabled")
    existing_owner = bs.get("owner_uid")
    if existing_owner and existing_owner != user_id:
        raise HTTPException(409, "This bot is already claimed by another user")

    _bind_bot_to_user(bot_uid, user_id, username)
    bot_email    = (auth.load_user_tokens(bot_uid) or {}).get("username", "bot")
    display_name = username.split("@")[0].replace(".", " ").title()
    background_tasks.add_task(_send_activation_greeting, bot_uid, username, display_name)

    return {"ok": True, "message": f"AI assistant ({bot_email}) is now monitoring {username}"}


@app.post("/api/teams/bot/disable")
def disable_bot(session: dict = Depends(require_session)):
    uid = session["user_id"]
    _unbind_bot_from_user(uid)
    path  = _bot_state_path(uid)
    state = json.loads(path.read_text()) if path.exists() else {}
    state["enabled"] = False
    _write_json(path, state)
    return {"ok": True}


# ── Graph test endpoint ───────────────────────────────────

@app.get("/api/admin/bot-bindings")
def admin_bot_bindings(session: dict = Depends(require_session)):
    sessions_dir = auth.DATA_DIR / "_sessions"
    results = []
    for tf in sessions_dir.glob("*.json"):
        bid = tf.stem
        bp  = _bot_state_path(bid)
        if not bp.exists():
            continue
        bs        = json.loads(bp.read_text())
        bot_email = (auth.load_user_tokens(bid) or {}).get("username", "")
        owner_uid = bs.get("owner_uid")
        owner_email = ""
        if owner_uid:
            ot = auth.load_user_tokens(owner_uid) or {}
            owner_email = ot.get("username", owner_uid)
        results.append({
            "bot_uid":      bid,
            "bot_email":    bot_email,
            "enabled":      bs.get("enabled", False),
            "owner_uid":    owner_uid,
            "owner_email":  owner_email,
            "peer_email":   bs.get("peer_email", ""),
            "last_seen_ts": bs.get("last_seen_ts"),
        })
    return results


@app.post("/api/admin/bot/unbind/{bot_uid}")
def admin_unbind_bot(bot_uid: str, session: dict = Depends(require_session)):
    bp = _bot_state_path(bot_uid)
    if not bp.exists():
        raise HTTPException(404, "Bot not found")
    bs = json.loads(bp.read_text())
    prev_owner = bs.get("owner_uid")
    bs.update({"owner_uid": None, "peer_email": None, "chat_id": None, "last_seen_ts": None})
    _write_json(bp, bs)
    if prev_owner:
        _user_bot_link_path(prev_owner).unlink(missing_ok=True)
    return {"ok": True, "bot_uid": bot_uid, "message": "Bot unbound successfully"}


@app.get("/api/test/graph")
def test_graph(session: dict = Depends(require_session)):
    uid = session["user_id"]
    try:
        token = auth.get_valid_access_token(uid)
        graph = GraphClient(token)
        me    = graph.get_me()
        msgs  = graph.get_messages(top=3)
        return {
            "ok":   True,
            "user": {
                "displayName":       me.get("displayName"),
                "mail":              me.get("mail"),
                "userPrincipalName": me.get("userPrincipalName"),
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


# ── Section registry ─────────────────────────────────────
# Add entries here as sections are implemented.

_SECTION_RUNNERS: dict[str, object] = {
    "ai_summary": lambda graph, ai, data_dir, settings, progress:
        ai_summary.run(graph, ai, data_dir, settings, progress),
    "expenses": lambda graph, ai, data_dir, settings, progress:
        expenses.run(graph, ai, data_dir, progress=progress),
}


def _format_section_for_teams(result: dict) -> str:
    section_id = result.get("id", "")
    if section_id == "ai_summary":
        return result.get("briefing", "")
    items = result.get("items", [])
    if not items:
        return ""
    title = section_id.replace("_", " ").title()
    lines = [f"**{title}** — {len(items)} item(s)"]
    for item in items[:5]:
        label = item.get("subject") or item.get("vendor") or item.get("title") or str(item)
        lines.append(f"• {str(label)[:80]}")
    if len(items) > 5:
        lines.append(f"• ... and {len(items) - 5} more")
    return "\n".join(lines)


def _send_to_bot(uid: str, result: dict) -> None:
    bot_uid, chat_id = _find_bot_for_user(uid)
    if not bot_uid or not chat_id:
        return
    message = _format_section_for_teams(result)
    if not message:
        return
    try:
        bot_token = auth.get_valid_access_token(bot_uid)
        bot_graph = GraphClient(bot_token)
        bot_graph.send_chat_message(chat_id, message)
    except Exception as e:
        print(f"[Bot] Failed to send {result.get('id')} to {uid}: {e}")


@app.post("/api/sections/{section_id}/run")
def run_section(section_id: str, background_tasks: BackgroundTasks,
                session: dict = Depends(require_session)):
    if section_id not in _SECTION_RUNNERS:
        raise HTTPException(404, detail=f"Section '{section_id}' not implemented yet")
    uid = session["user_id"]

    results_dir = _udir(uid) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results_dir / f"{section_id}.json", {
        "id": section_id, "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    def _run():
        logs: list[str] = []

        def _progress(msg: str):
            logs.append(msg)
            print(f"[Section:{section_id}] {msg}")
            _write_json(results_dir / f"{section_id}.json", {
                "id": section_id, "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "logs": logs[-20:],
            })

        try:
            token    = auth.get_valid_access_token(uid)
            graph    = GraphClient(token)
            ai       = AIClient()
            settings = _read_json(_user_settings(uid))

            result = _SECTION_RUNNERS[section_id](
                graph, ai, _udir(uid), settings, _progress,
            )
            result["logs"] = logs
            _write_json(results_dir / f"{section_id}.json", result)
            _send_to_bot(uid, result)
            print(f"[Section:{section_id}] Done for {uid}")
        except Exception as e:
            _write_json(results_dir / f"{section_id}.json", {
                "id": section_id, "status": "error",
                "error": str(e),
                "logs": logs,
                "last_run": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[Section:{section_id}] Failed for {uid}: {e}")

    background_tasks.add_task(_run)
    return {"ok": True}


@app.get("/api/sections/{section_id}")
def get_section(section_id: str, session: dict = Depends(require_session)):
    uid  = session["user_id"]
    path = _udir(uid) / "results" / f"{section_id}.json"
    if not path.exists():
        return {"id": section_id, "status": "not_run", "items": [], "count": 0, "empty": True}
    return _read_json(path)


@app.get("/api/sections/{section_id}/instructions")
def get_section_instructions(section_id: str, session: dict = Depends(require_session)):
    uid  = session["user_id"]
    path = _udir(uid) / "instructions" / f"{section_id}.md"
    return {"content": path.read_text() if path.exists() else ""}


@app.put("/api/sections/{section_id}/instructions")
def update_section_instructions(section_id: str, body: dict, session: dict = Depends(require_session)):
    uid  = session["user_id"]
    path = _udir(uid) / "instructions" / f"{section_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.get("content", ""))
    return {"ok": True}


def _run_section_for_user(uid: str, section_id: str) -> None:
    """Run a section directly (no HTTP). Used by bot.py to trigger sections from Teams chat."""
    if section_id not in _SECTION_RUNNERS:
        print(f"[Section:{section_id}] Not implemented — skipping")
        return
    results_dir = _udir(uid) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results_dir / f"{section_id}.json", {
        "id": section_id, "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        token    = auth.get_valid_access_token(uid)
        graph    = GraphClient(token)
        ai       = AIClient()
        settings = _read_json(_user_settings(uid))
        result   = _SECTION_RUNNERS[section_id](graph, ai, _udir(uid), settings, None)
        _write_json(results_dir / f"{section_id}.json", result)
        _send_to_bot(uid, result)
        print(f"[Section:{section_id}] Done (bot-triggered) for {uid}")
    except Exception as e:
        _write_json(results_dir / f"{section_id}.json", {
            "id": section_id, "status": "error", "error": str(e),
            "last_run": datetime.now(timezone.utc).isoformat(),
        })
        print(f"[Section:{section_id}] Failed (bot-triggered) for {uid}: {e}")


# ── CRM ──────────────────────────────────────────────────

@app.get("/api/crm")
def get_crm(session: dict = Depends(require_session)):
    uid      = session["user_id"]
    crm_path = _udir(uid) / "crm.json"
    if not crm_path.exists():
        return {"last_scan": None, "months_scanned": 0, "total": 0, "contacts": []}
    try:
        data     = json.loads(crm_path.read_text())
        contacts = list(data.get("contacts", {}).values())
        contacts.sort(key=lambda x: x.get("last_contact", ""), reverse=True)
        return {
            "last_scan":      data.get("last_scan"),
            "months_scanned": data.get("months_scanned", 0),
            "total":          len(contacts),
            "contacts":       contacts,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.patch("/api/crm/{email}")
def patch_crm_contact(email: str, body: dict, session: dict = Depends(require_session)):
    uid  = session["user_id"]
    from src.modules.crm import load_crm, save_crm
    data = load_crm(_udir(uid))
    addr = email.lower()
    if addr not in data.get("contacts", {}):
        raise HTTPException(404, "Contact not found")
    data["contacts"][addr].update(body)
    save_crm(_udir(uid), data)
    return data["contacts"][addr]


@app.post("/api/crm/scan")
def trigger_crm_scan(background_tasks: BackgroundTasks,
                     session: dict = Depends(require_session),
                     months: int = 6):
    uid = session["user_id"]

    def _run():
        try:
            from src.modules.crm import build_crm, save_crm
            from src.ai import AIClient
            token = auth.get_valid_access_token(uid)
            graph = GraphClient(token)
            ai    = AIClient()
            result = build_crm(graph, ai, _udir(uid), months=months)
            save_crm(_udir(uid), result)
            print(f"[CRM] Scan complete for {uid}: {result['total']} contacts")
        except Exception as e:
            print(f"[CRM] Scan failed for {uid}: {e}")

    background_tasks.add_task(_run)
    return {"ok": True, "message": "CRM scan started"}


# ── Health check ──────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Startup ───────────────────────────────────────────────

_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")


@app.on_event("startup")
def startup_event():
    _scheduler.start()
    _scheduler.add_job(
        _poll_teams_bot_all_users,
        trigger="interval",
        seconds=10,
        id="teams_bot_poll",
        replace_existing=True,
        max_instances=1,
    )
    print("[TeamsBot] Polling every 10 seconds")
