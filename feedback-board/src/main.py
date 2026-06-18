"""feedback-board — internal team AI Q&A + bug/feature request board.

Isolated standalone service (mirrors ops-dashboard). Does NOT import the main
program's `src/`; never writes the main app's `.data/`. Two-tier HTTP Basic Auth:
  - TEAM_PASSWORD  → team page, chat, submit/list requests
  - ADMIN_USER/ADMIN_PASSWORD → change request status, delete

Layout:
  GET  /                         → static/index.html (team auth)
  GET  /health                   → public healthcheck
  GET  /api/requests             → list requests (team auth)
  POST /api/requests             → create a request (team auth)
  POST /api/requests/{id}/status → change status (admin auth)
  POST /api/chat                 → KB-grounded Q&A (team auth)   [Phase 3]
  POST /webhook/github           → push → auto-close REQ-N       [Phase 4]
"""
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import kb_loader, state, webhook

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("feedback.main")

STATIC_DIR = Path(__file__).parent.parent / "static"

basic = HTTPBasic()


# ── Auth (two tiers) ──────────────────────────────────────

def _admin_ok(creds: HTTPBasicCredentials) -> bool:
    user = os.getenv("ADMIN_USER", "")
    pw = os.getenv("ADMIN_PASSWORD", "")
    if not user or not pw:
        return False
    return (secrets.compare_digest(creds.username.encode(), user.encode())
            and secrets.compare_digest(creds.password.encode(), pw.encode()))


def require_team(creds: HTTPBasicCredentials = Depends(basic)) -> str:
    """Team gate: the shared TEAM_PASSWORD (any username), OR valid admin creds.
    Fail closed if TEAM_PASSWORD is unset."""
    team_pw = os.getenv("TEAM_PASSWORD", "")
    if not team_pw:
        raise HTTPException(503, "TEAM_PASSWORD not configured")
    if secrets.compare_digest(creds.password.encode(), team_pw.encode()) or _admin_ok(creds):
        return creds.username or "team"
    raise HTTPException(
        status_code=401,
        detail="Invalid team credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


def require_admin(creds: HTTPBasicCredentials = Depends(basic)) -> str:
    if not os.getenv("ADMIN_USER") or not os.getenv("ADMIN_PASSWORD"):
        raise HTTPException(503, "ADMIN_USER/ADMIN_PASSWORD not configured")
    if _admin_ok(creds):
        return creds.username
    raise HTTPException(
        status_code=401,
        detail="Invalid admin credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


# ── Request/response models ───────────────────────────────

class NewRequest(BaseModel):
    kind: str
    title: str
    body: str = ""
    author: str = "anonymous"
    chat_context: str | None = None


class StatusChange(BaseModel):
    status: str


class ChatRequest(BaseModel):
    question: str


# Lazy Gemini client — created on first chat so the service still boots (health,
# board) without a GEMINI_API_KEY configured.
_ai = None


def _get_ai():
    global _ai
    if _ai is None:
        from .ai import AIClient
        _ai = AIClient()
    return _ai


# ── App ───────────────────────────────────────────────────

app = FastAPI(title="CEO Platform Feedback Board")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root(_: str = Depends(require_team)):
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"error": "index.html missing"}, status_code=500)
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/api/requests")
def api_list_requests(_: str = Depends(require_team)):
    return {"requests": state.list_requests()}


@app.post("/api/requests")
def api_create_request(body: NewRequest, who: str = Depends(require_team)):
    try:
        req = state.add_request(
            kind=body.kind,
            title=body.title,
            body=body.body,
            author=body.author or who,
            chat_context=body.chat_context,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log.info("created %s (%s) by %s", req["id"], req["kind"], req["author"])
    return req


@app.post("/api/requests/{req_id}/status")
def api_set_status(req_id: str, body: StatusChange, admin: str = Depends(require_admin)):
    try:
        req = state.set_status(req_id, body.status, actor=admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not req:
        raise HTTPException(404, f"{req_id} not found")
    log.info("%s status → %s by %s", req_id, body.status, admin)
    return req


@app.post("/api/chat")
def api_chat(body: ChatRequest, _: str = Depends(require_team)):
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(503, "chat unavailable — GEMINI_API_KEY not configured")
    prompt, sections = kb_loader.build_prompt(question)
    try:
        answer = _get_ai().generate(prompt)
    except Exception as e:  # noqa: BLE001
        log.warning("chat generate failed: %s", e)
        raise HTTPException(502, "the assistant is temporarily unavailable")
    return {"answer": answer, "sections": sections}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET not configured")
    body = await request.body()
    if not webhook.verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(401, "invalid signature")
    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    if x_github_event and x_github_event != "push":
        return {"ok": True, "ignored_event": x_github_event}
    payload = await request.json()
    result = webhook.apply_closures(webhook.extract_closures(payload))
    if result["closed"]:
        log.info("webhook closed: %s", result["closed"])
    return {"ok": True, **result}
