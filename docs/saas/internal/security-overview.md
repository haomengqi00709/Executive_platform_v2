# Security overview — SaaS tier

**Audience:** internal team (Jason, partner). May be shared with a
customer's security team on request as a high-level architecture summary.

**Scope:** the multi-tenant SaaS deployment on Railway. BYOC and CPDP
tiers have their own security overviews (see `docs/byoc/` and
`docs/cpdp/`).

## 1. Architecture

```
                  ┌─────────────────────────────────────────┐
                  │  Railway (US-east)                      │
                  │                                         │
   Customer ─────►│  FastAPI app                            │
   browser        │    ├─ /auth (OAuth flow + JWT cookies)  │
                  │    ├─ /api/* (per-user data access)     │
                  │    └─ scheduled jobs (briefing, email,  │
                  │       meeting poll, etc.)               │
                  │                                         │
                  │  Per-user data dir: .data/{user_id}/    │
                  │    ├─ wiki/, results/, transcripts/     │
                  │    ├─ settings.json, crm.json, etc.     │
                  │    └─ OAuth tokens (encrypted at rest)  │
                  │                                         │
                  └────────┬──────────────────┬─────────────┘
                           │                  │
                           ▼                  ▼
                  Microsoft Graph        Google Gemini
                  (mail, calendar,       (AI processing
                   OneDrive, Teams)       of text, audio,
                                          video)
```

## 2. Authentication

- **Mechanism**: Microsoft OAuth 2.0 Authorization Code Flow, via MSAL.
- **No passwords stored**: Microsoft handles user authentication entirely.
- **Multi-tenant**: the Azure AD application is registered against
  `/common`, so users from any Microsoft tenant can sign in.
- **Token storage**: per-user under `.data/{user_id}/` (encrypted at rest
  by Railway).
- **Refresh**: access tokens are auto-refreshed with a 5-minute expiry
  buffer.

## 3. Session management

- **JWT cookie**: HTTP-only, `Secure` flag auto-enabled when
  `REDIRECT_URI` starts with `https://`, `SameSite=lax`.
- **Lifetime**: 7 days.
- **Signing key**: `SESSION_SECRET` env var; the app fails fast at
  startup if it is unset or set to the dev default value.

## 4. Authorization (multi-tenant isolation)

Every authenticated API request follows the same shape:

1. Reads the `session_token` cookie.
2. Validates and decodes the JWT to recover `user_id`.
3. Uses **only** that session-derived `user_id` to construct the data
   path `.data/{user_id}/`.

Critically, `user_id` is **never** taken from a query parameter, request
body, or URL path — it always comes from the validated session. This is
the primary defense against cross-user data leaks, and the code is
audited to maintain this invariant.

## 5. Encryption

- **In transit**: TLS 1.3 (Railway-managed certificates).
- **At rest**: AES-256 (Railway platform default for all managed storage).
- **OAuth refresh tokens**: stored in the at-rest-encrypted volume; not
  separately encrypted at the application layer. This is acceptable
  because the volume itself is encrypted and access requires Railway
  account access. Application-layer encryption is on the roadmap for
  defense-in-depth.

## 6. Secrets management

All secrets are env-var driven. The app calls `_required_env()` at module
load time and refuses to start if any required secret is missing or
empty:

- `PROD_CLIENT_ID`, `PROD_CLIENT_SECRET` — Microsoft Entra ID app
  credentials.
- `TENANT_ID` — multi-tenant config (set to `common` for SaaS).
- `SESSION_SECRET` — JWT signing key (must not equal the dev default).
- `GEMINI_API_KEY` — Google Gemini API access.

No secret is hardcoded in source. Phase B (May 2026) removed all
hardcoded fallbacks and known dev defaults from production paths.

## 7. CORS

Restricted to the `FRONTEND_URL` allowlist. Defaults to `localhost:3000`
for dev; production overrides to the deployed origin. Wildcard origins
are explicitly disallowed.

## 8. Filesystem write safety

- **Atomic JSON writes**: all settings and state files use the temp-file
  + `os.replace` pattern. This defends against partial-write corruption
  (originally observed on a different storage backend — Azure Files SMB)
  and is retained for safety on Railway.
- **SQLite WAL mode**: used for the bot conversation history database to
  allow concurrent reads during writes and reduce corruption risk on
  shared storage.

## 9. Sub-processor security posture

| Sub-processor | Relevant certifications |
|---|---|
| Microsoft Graph | SOC 1/2/3, ISO 27001/27017/27018, HIPAA, FedRAMP, GDPR |
| Google Gemini | SOC 1/2/3, ISO 27001/27017/27018/27701, GDPR |
| Railway | SOC 2 (verify current status with Railway before claiming) |

## 10. Threat model — what we defend against

- **Cross-user data leak**: session-derived `user_id` only.
- **Token theft**: HTTP-only, Secure cookies; short-lived access tokens.
- **CSRF**: `SameSite=lax` on session cookie; OAuth `state` parameter
  enforced.
- **Open redirect**: OAuth redirect targets must match a registered URI.
- **Injection**: no raw SQL; storage is file-based or parameterized.
- **Secret leak via logs**: env values are not logged; the Phase B audit
  removed hardcoded fallbacks that could have leaked under fail-open
  conditions.
- **Replay**: OAuth `state`; JWT `iat`/`exp` claims.

## 11. Threat model — what we do NOT defend against (yet)

- **Insider threat (Jason / partner)**: no two-person rule for production
  access. Mitigated only by smallness of the team.
- **Sub-processor compromise**: a breach at Microsoft or Google is outside
  our control. We monitor their status pages.
- **Sophisticated targeted attacks**: no WAF, no DDoS mitigation beyond
  Railway's defaults.
- **Code supply-chain attacks**: dependencies are pinned in
  `requirements.txt`, but no automated vulnerability scanning runs yet.
- **Forensic-quality audit trail**: app logs exist (30-day retention) but
  there is no dedicated audit log of vendor (human) access. Customers
  who need this should consider the BYOC tier, where Azure Activity Log
  provides it natively.

## 12. Future hardening (planned, not done)

- Customer-facing security dashboard ("vendor accessed your data 0 times
  this month").
- Application-level audit logging for vendor access.
- Dependency vulnerability scanning in CI (Dependabot or equivalent).
- Off-site encrypted backup (currently relying on Railway's daily
  snapshots).
- SOC 2 Type I (gated on a customer requiring it).
