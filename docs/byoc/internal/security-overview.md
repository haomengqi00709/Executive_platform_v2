# Security overview — BYOC tier

**Audience:** internal team. May be shared with a customer's security
team on request.

**Scope:** single-tenant deployments where the platform runs in the
customer's own Azure subscription. See `docs/saas/internal/` for the
multi-tenant SaaS equivalent.

## 1. Architecture

```
                  ┌─────────────────────────────────────────────────┐
                  │  Customer's Azure subscription                  │
                  │                                                 │
                  │  ┌─ App Service (Linux Container) ──────────┐  │
   Customer ────► │  │ FastAPI app                              │  │
   browser        │  │   ├─ /auth (OAuth flow + JWT cookies)    │  │
                  │  │   ├─ /api/* (single-user data access)    │  │
                  │  │   └─ scheduled jobs                      │  │
                  │  │                                          │  │
                  │  │ Mount: /mnt/data → Azure Files share     │  │
                  │  │   └─ .data/{user_id}/                    │  │
                  │  └──────────────────────────────────────────┘  │
                  │                                                 │
                  │  ┌─ Azure Container Registry ───────────────┐  │
                  │  │ Image: ceo-platform:<tag>                │  │
                  │  │ Built by vendor; pulled by App Service   │  │
                  │  └──────────────────────────────────────────┘  │
                  │                                                 │
                  │  ┌─ Storage Account ────────────────────────┐  │
                  │  │ Azure Files share: customer's data       │  │
                  │  │ AES-256 at rest (Microsoft default)      │  │
                  │  └──────────────────────────────────────────┘  │
                  └─────────┬───────────────────┬───────────────────┘
                            │                   │
                            ▼                   ▼
                  Microsoft Graph         Google Gemini
                  (mail, calendar,        (AI processing)
                   OneDrive, Teams)
```

## 2. Authentication

Same as SaaS:

- Microsoft OAuth 2.0 Authorization Code Flow via MSAL.
- No password storage.
- Multi-tenant Entra ID app (registered against `/common`).
- Token storage under customer's Azure Files share.
- Refresh with 5-minute expiry buffer.

## 3. Session management

Same as SaaS: HTTP-only Secure JWT cookie, 7-day lifetime,
`SameSite=lax`, signed with `SESSION_SECRET`.

## 4. Authorization (multi-tenant isolation)

The application is structured for multi-tenancy even though a BYOC
deployment typically has one primary user. The `user_id` is always
derived from the validated session and used to construct
`.data/{user_id}/` — never from a request parameter.

## 5. Encryption

- **In transit**: TLS 1.3 (Azure-managed certificates on App Service).
- **At rest**: AES-256 (Azure Storage SSE, default).
- **OAuth refresh tokens**: stored in the Azure Files share (encrypted
  at rest by Azure).

## 6. Secrets management

Same fail-fast pattern as SaaS. Secrets live in Azure App Service
Configuration. Roadmap: move to Azure Key Vault references so customer
IT controls access.

## 7. CORS

Restricted to `FRONTEND_URL` (the App Service URL).

## 8. Filesystem write safety (critical for Azure Files)

Phase B introduced atomic writes specifically because Azure Files (SMB)
exhibited partial-write corruption under concurrent writes. All
settings and state files use temp-file + `os.replace`.

SQLite for the bot conversation history uses WAL mode for the same
reason.

## 9. Vendor (human) access protocol

- **Default**: vendor has **no standing access** to customer data.
- Vendor access is via a service principal granted RBAC role by the
  customer.
- **Recommended role scope**: Contributor on the platform's resource
  group only (not subscription-wide).
- **Stronger option**: custom role allowing only App Service operations
  (read logs, restart, swap image) and no Storage read access.
- Every vendor action is logged in the customer's Azure Activity Log.
- Customer can revoke the role at any time.

**Vendor commitments**:

- Notify the customer 24h in advance of routine debug access.
- Notify the customer within 24h after emergency access.
- Never read user data files unless required to reproduce a customer-
  reported bug, and only with customer awareness.

## 10. Sub-processor security posture

| Sub-processor | Relevant certifications |
|---|---|
| Microsoft Graph | SOC 1/2/3, ISO 27001/27017/27018, HIPAA, FedRAMP, GDPR |
| Google Gemini | SOC 1/2/3, ISO 27001/27017/27018/27701, GDPR |
| Customer's own Azure subscription | Whatever Microsoft provides + customer's own compliance posture |

## 11. Threat model — what we defend against

Same as SaaS, plus:

- **Cross-customer data leak**: structurally impossible — each customer
  has their own Azure subscription. No shared infrastructure.
- **Vendor over-reach**: customer audit via Activity Log; customer can
  revoke access; RBAC role scope limits what vendor can touch.

## 12. Threat model — what we do NOT defend against (yet)

- **Customer Azure admin misconfiguration**: if the customer opens up
  their Storage account to public access, that's on them.
- **Customer's own subscription compromise**: not in our scope.
- **Sub-processor compromise**: same as SaaS.
- **Audit log of vendor application-level access**: Azure Activity Log
  covers Azure-level operations, not what the application does inside
  itself. A future feature would surface application-level audit
  separately.

## 13. Per-customer hardening (referenced from onboarding)

For each new BYOC deployment, the onboarding runbook performs these
one-time hardening steps:

- App Service identity (Managed Identity preferred over admin key).
- Storage account: deny public network access; allow App Service VNet
  only (advanced).
- Container Registry: admin user disabled where possible; use Managed
  Identity for pulls.
- App Service: HTTPS-only enforced; TLS 1.2 minimum.
- Diagnostic logs: enabled and sent to customer Log Analytics
  workspace if customer has one.
- Resource group: locked with `CanNotDelete` to prevent accidental
  deletion (customer can override).
