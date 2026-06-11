# Deployment runbook — CPDP tier (PLANNED)

**Audience:** Jason. Future tier.

> **CPDP not yet built. This doc describes the planned operations
> model and will be revised when the implementation lands.**

CPDP deployment has **two parts**:

1. **CP**: deploy and operate the central control plane (one
   instance, shared across all CPDP customers).
2. **DP**: deploy a per-customer data plane in their Azure (mostly
   the same as BYOC).

This runbook covers both.

## 1. CP-side operations

The CP is essentially our own SaaS. Standard SaaS ops apply.

### 1.1 Stack (planned)

- FastAPI for API endpoints (skills, config, telemetry).
- PostgreSQL for customer registry + prompts + telemetry.
- Azure Key Vault for the signing key.
- Hosted on Railway or vendor's own Azure subscription (TBD at launch).

### 1.2 Required env vars (CP)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PG connection string |
| `SIGNING_KEY_VAULT_URL` | Azure Key Vault URL for the signing key |
| `SESSION_SECRET` | JWT signing for admin dashboard |
| `ALERTING_WEBHOOK` | PagerDuty / Slack for incidents |

### 1.3 Deploy flow (CP)

Same as our SaaS: push to main, CI builds image, deploys to Railway
(or vendor's Azure).

### 1.4 Monitoring (critical for CP)

- Uptime monitor on `/api/v1/health`.
- Per-customer request volume.
- Error rate.
- Signing operation log.

### 1.5 Rotation

- **API keys**: rotate per customer quarterly.
- **Signing key**: rotate per CP security policy (annual; emergency
  on suspected compromise).
- **Database password**: rotate per vendor SaaS policy.

## 2. DP-side operations

The DP is mostly the same as BYOC (see
`docs/byoc/operations/deployment-runbook.md`). Specific differences:

- Container image is a thinner version (only the runtime, not the
  full app with prompts).
- Additional env vars:
  - `CP_URL` — CP endpoint.
  - `CP_API_KEY` — per-customer API key issued by CP.
  - `CP_SIGNING_PUBLIC_KEY` — embedded in image (verified at fetch).
  - `PINNED_BUNDLE_HASH` (optional) — if customer pins.

### 2.1 Build and deploy flow (DP)

Same as BYOC. The image is rebuilt when DP runtime code changes;
prompts and config do not require rebuild (they're served by the CP).

### 2.2 DP common operations

Same as BYOC.

### 2.3 DP-specific operations

- **Rotate `CP_API_KEY`**: customer admin gets new key from CP
  dashboard; update env var; restart App Service.
- **Pin a bundle hash**: set `PINNED_BUNDLE_HASH` env var; restart.
- **Force cache refresh**: restart App Service.

## 3. Cross-plane operations

### 3.1 Customer wants the latest bundle pushed

CP dashboard → customer record → "Apply latest". DP pulls on next
refresh (TTL 7 days, or restart for immediate).

### 3.2 Customer wants to roll back to a specific bundle

CP dashboard → customer record → pin bundle hash. DP pulls and
stays on the pinned hash.

### 3.3 Customer reports stale config

1. Verify CP shows the bundle as available.
2. Check DP cache: SSH into DP container, inspect `.cache/`.
3. Restart DP App Service to force refresh.

## 4. Disaster scenarios

| Scenario | Response |
|---|---|
| CP completely down | DPs continue on cached config for 7 days. Restore CP from snapshot. |
| Specific customer's DP down | Per BYOC. CP unaffected. |
| Signing key compromised | Disaster: rotate signing key, re-sign all current bundles, all DPs need updated image with new public key. |
| API key for one customer leaked | Revoke + issue new. DP needs env var update. |
