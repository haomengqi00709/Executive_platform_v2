# ops-dashboard

Standalone monitoring + alerting service for the CEO platform fleet.

## What it does

Polls the main backend's `/api/admin/fleet-health` endpoint every 60s, caches
the result, and pushes Teams + email alerts whenever a user/bot transitions
from healthy → broken (or back). A minimal HTML dashboard at `/` shows the
current state.

It monitors four things, each fail-safe and deduped to one page per
`ALERT_REPEAT_HOURS`:

1. **Auth health** — per-user/bot MS token refresh (healthy ↔ broken edges).
2. **Backend liveness** — whether the poller can reach the backend at all
   (one fleet-level alert, never N per-user — see below).
3. **Scheduled jobs** — whether each background job (briefings, email monitor,
   the canary probe, …) is actually succeeding, via `last_success` age and
   consecutive-failure count surfaced in `fleet-health.jobs`.
4. **Push quality** — when the backend's `PUSH_QA_ENABLED` sampler is on, the
   per-user quality verdicts (`fleet-health.push_qa`) are shown and a `fail`
   pages ops. Quality scoring itself lives in the main backend
   (`src/modules/push_qa.py`); the dashboard only displays + alerts on it.

It also watches its own poll: if the main backend is unreachable for
`POLL_FAIL_THRESHOLD` consecutive polls (default 3 ≈ 3 min), it fires ONE
fleet-level `backend_unreachable` alert (not one per account) and a
`backend_recovered` alert when it comes back. A heartbeat banner on the
dashboard shows backend liveness. This closes the fail-silent gap where a
total backend outage would otherwise produce no signal at all.

## Architecture

```
ops-dashboard ── 60s poll ──▶ main backend /api/admin/fleet-health
      │
      ├── data/fleet_summary.json    (latest snapshot, served to /api/state)
      ├── data/fleet_summary_prev.json (previous, for diffing)
      ├── data/poll_health.json     (backend liveness: failure streak, last success)
      └── data/alert_history.json   (dedup so the same break doesn't spam every 60s)
```

## Routes

| Path | Auth | Purpose |
|---|---|---|
| `GET /` | HTTP Basic | Dashboard HTML |
| `GET /api/state` | HTTP Basic | Latest snapshot JSON |
| `GET /api/poll-health` | HTTP Basic | Backend liveness (drives the heartbeat banner) |
| `POST /webhook/event` | `X-Admin-Token` | Inbound event receiver (scaffolded, unused) |
| `GET /health` | none | Healthcheck for Railway/Azure |

## Local dev

```bash
cd ops-dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values
uvicorn src.main:app --reload --port 9000
```

Browser → http://localhost:9000 → Basic Auth prompt.

## Deployment

### Railway (priority 1)

1. Push to main
2. Railway dashboard → new service in `zippy-quietude` project
3. Connect GitHub repo, set root directory `ops-dashboard/`
4. Set env vars from `.env.example`
5. Add volume mount at `/data`, set `DATA_DIR=/data`
6. Generate domain

### Azure (priority 2)

```bash
az acr build --registry ceoplatformv2acr --image ops-dashboard:v1 \
  --image ops-dashboard:latest --platform linux/amd64 \
  -f ops-dashboard/Dockerfile ops-dashboard/

# Create App Service ceo-ops-dashboard (B1 Linux Container)
az webapp config container set --name ceo-ops-dashboard \
  --resource-group ceo-platform \
  --docker-custom-image-name ceoplatformv2acr.azurecr.io/ops-dashboard:v1

# Mount Azure Files share at /mnt/data/ops, set DATA_DIR=/mnt/data/ops
```
