# Deployment runbook — SaaS tier (Railway)

**Audience:** Jason (and any future engineer with deploy responsibility).

## 1. Project setup

- Platform: Railway (https://railway.app)
- Project: **_TBD — fill in link or service IDs_**
- Service name: `ceo-platform-saas` (or current name)
- Region: US-east (Railway default)
- Plan: **_TBD — Hobby / Pro_**

GitHub repo connected for auto-deploy from the `main` branch.

## 2. Required environment variables

The app calls `_required_env()` for the critical ones and refuses to
start if any are missing. The runbook below lists every variable the
code reads.

### 2.1 Required (app crashes on startup if missing)

| Variable | Purpose | How to obtain |
|---|---|---|
| `PROD_CLIENT_ID` | Microsoft Entra ID app client ID | Entra ID portal → App registrations → Overview |
| `PROD_CLIENT_SECRET` | Microsoft Entra ID app client secret | Entra ID portal → Certificates & secrets |
| `TENANT_ID` | Multi-tenant config: set to `common` for SaaS | Hardcoded `common` for SaaS tier |
| `SESSION_SECRET` | JWT signing key (must NOT equal the dev default) | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `GEMINI_API_KEY` | Google Gemini API access | https://aistudio.google.com/apikey |

### 2.2 Deployment-specific (must be set per environment)

| Variable | Purpose | SaaS value |
|---|---|---|
| `DATA_DIR` | Where per-user data lives | `/data` (Railway volume mount) or default `.data/` |
| `REDIRECT_URI` | OAuth callback URL | `https://<railway-url>/auth/callback` |
| `FRONTEND_URL` | Allowed CORS origin (comma-separated for multiple) | `https://<railway-url>` |
| `APP_URL` | Public app URL used in outbound emails | `https://<railway-url>` |

### 2.3 Optional

| Variable | Purpose | SaaS default |
|---|---|---|
| `CLIENT_ID` | Device-flow client ID (used for bot registration) | Falls back to dev value with warning if unset |
| `BETA_ALLOWLIST` | Comma-separated list of invited beta emails (lowercase) | Unset = open to anyone with M365; set = locked down to listed emails |

## 3. Build and deploy flow

```
git push origin main
       │
       ▼
GitHub webhook → Railway
       │
       ▼
Railway builds container per nixpacks.toml (Python 3.13, ffmpeg, etc.)
       │
       ▼
Railway deploys new container; old container served until new one is
healthy
       │
       ▼
New container live (~3-5 minutes after push)
```

To pause auto-deploy (e.g., before risky changes): Railway dashboard →
Settings → uncheck "Deploy on push".

## 4. Health check

`GET /api/auth/status` should return 200 with `{"authenticated": false}`
on an unauthenticated request. UptimeRobot pings this every 5 minutes
and emails Jason on failure.

## 5. Rollback procedure

1. Railway dashboard → Deployments tab.
2. Locate the last known-good deployment.
3. Click "Redeploy".
4. Verify the health check returns 200.
5. If rollback succeeded, investigate the bad deploy without time
   pressure.

## 6. Logs access

- **Live tail**: Railway dashboard → service → Logs tab.
- **Search**: the Logs tab has a search box; works on plain text.
- **Download**: not directly supported via UI; pipe via Railway CLI
  (`railway logs`) or copy/paste from UI.

## 7. Common operations

### 7.1 Restart the service

Railway dashboard → service → Settings → "Restart service".

### 7.2 Update an env var

1. Railway dashboard → service → Variables tab.
2. Edit or add the variable.
3. Save.
4. Railway automatically restarts the service (~30 seconds).
5. Verify the change took effect via logs or behavior.

### 7.3 Rotate `SESSION_SECRET`

1. Generate new value:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Update env var per 7.2.
3. All users will be logged out and need to re-sign-in.
4. Schedule for a low-traffic window if possible.

### 7.4 Rotate `PROD_CLIENT_SECRET`

1. Entra ID portal → app → Certificates & secrets → new client secret.
2. Update the Railway env var (don't delete the old secret yet).
3. Verify a sign-in works.
4. Delete the old secret in Entra ID.

### 7.5 Scale up (when traffic exceeds 1 instance)

Railway dashboard → service → Settings → Resources. Beta is
single-instance. Multi-instance requires:

- Session affinity is already fine (sessions are JWT-only, no
  server-side state).
- Background schedulers (APScheduler) would multiply across instances
  and double-trigger. Migrate to a single-leader pattern (Redis lock or
  dedicated scheduler service) before scaling out.

## 8. Multi-region considerations (future)

Currently single-region (US-east). EU residency requires:

- A separate Railway project in eu-west.
- Routing logic at the OAuth state level to pick the right backend.
- This is non-trivial and gated on EU customer demand.

## 9. Disaster scenarios

| Scenario | Response |
|---|---|
| Railway region outage | No fallback. Wait for Railway. Communicate via partner channels. |
| GitHub Actions down | Manual `railway up` from local CLI. |
| Microsoft Graph API down | Wait. Inform customers. No fallback available. |
| Gemini API down | Modules that depend on Gemini fail gracefully (log error, skip). Email and chat flows continue. |
| Lost access to Railway account | Recovery via Railway support + 2FA reset. Maintain a backup access path for the partner. |
