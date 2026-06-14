"""
ops-dashboard FastAPI app — Basic-Auth-gated read-only fleet monitor.

Layout:
  GET /            → static/index.html (Basic Auth)
  GET /api/state   → latest snapshot JSON (Basic Auth)
  POST /webhook/event → inbound event receiver (X-Admin-Token; scaffold)
  GET /health      → public healthcheck

Background: APScheduler runs poller.run() every POLL_INTERVAL_SECS (default 60).
"""
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import poller, state

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("ops.main")

POLL_INTERVAL_SECS = int(os.getenv("POLL_INTERVAL_SECS", "60"))
STATIC_DIR = Path(__file__).parent.parent / "static"


# ── Basic Auth ────────────────────────────────────────────

basic = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(basic)):
    user = os.getenv("OPS_ADMIN_USER", "")
    pw   = os.getenv("OPS_ADMIN_PASSWORD", "")
    if not user or not pw:
        # Fail closed: if env not configured, no one gets in.
        raise HTTPException(503, "OPS_ADMIN_USER/PASSWORD not configured")
    user_ok = secrets.compare_digest(creds.username.encode(), user.encode())
    pw_ok   = secrets.compare_digest(creds.password.encode(), pw.encode())
    if not (user_ok and pw_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


# ── Scheduler lifespan ────────────────────────────────────

scheduler = BackgroundScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Durability sanity check: alert_history.json + poll_health.json live in
    # DATA_DIR. If it's the ephemeral default, a redeploy wipes dedup state and
    # the 6h re-alert suppression resets — warn loudly so prod mounts a volume.
    data_dir = state.DATA_DIR
    if not data_dir.is_absolute() or str(data_dir) in ("./data", "data"):
        log.warning(
            "DATA_DIR=%s looks ephemeral — mount a persistent volume in prod "
            "(Railway volume / Azure Files), else alert dedup + heartbeat state "
            "reset on every redeploy", data_dir,
        )
    else:
        log.info("DATA_DIR=%s (persistent)", data_dir)

    scheduler.add_job(
        poller.run,
        "interval",
        seconds=POLL_INTERVAL_SECS,
        id="fleet_poll",
        max_instances=1,
        coalesce=True,
        # NOTE: do NOT pass next_run_time=None here — in APScheduler that adds the
        # job PAUSED (next_run_time stays None) so the interval never fires and the
        # monitor goes silent after the one eager poll below. Omitting it lets the
        # scheduler compute the normal first fire time (now + interval).
    )
    scheduler.start()
    log.info("scheduler started — polling every %ds", POLL_INTERVAL_SECS)

    # Eager first poll so the dashboard isn't empty on cold start.
    try:
        poller.run()
    except Exception as e:
        log.warning("initial poll failed: %s", e)

    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="CEO Platform Ops Dashboard", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root(_: str = Depends(require_admin)):
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"error": "dashboard html missing"}, status_code=500)
    # Never cache the dashboard shell — an ops view must always reflect the
    # latest deploy, not a stale copy the browser cached on a prior visit.
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/api/state")
def api_state(_: str = Depends(require_admin)):
    snapshot = state.load_current()
    if not snapshot:
        return {"empty": True, "message": "no poll has completed yet"}
    return snapshot


@app.get("/api/poll-health")
def api_poll_health(_: str = Depends(require_admin)):
    """Backend liveness — whether the poller can reach the main backend.
    Drives the heartbeat banner so a backend outage isn't silent."""
    return state.load_poll_health()


@app.post("/webhook/event")
async def webhook_event(
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Scaffolded inbound endpoint. Not wired to the main backend yet —
    here so we can add push-from-main events later without a redeploy
    cycle. Auth: same OPS_ADMIN_TOKEN shared secret as the outbound poll."""
    expected = os.getenv("OPS_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(503, "OPS_ADMIN_TOKEN not configured")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "invalid admin token")
    body = await request.json()
    log.info("inbound event: %s", body)
    return {"received": True}
