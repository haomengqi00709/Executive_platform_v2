# Security overview — CPDP tier (PLANNED)

**Audience:** internal team.

> **This describes the planned CPDP architecture. The code does not
> yet exist; this doc will be revised when the implementation lands.**

## 1. Architecture

```
┌──────────────────────────────────┐         ┌──────────────────────────────────────┐
│  Vendor CP (our SaaS)            │         │  Customer's Azure subscription       │
│                                  │         │                                      │
│  📦 Prompts library (PG)         │ ──pull──► │  ⚙️  DP runtime (FastAPI)            │
│  📦 Orchestration definitions    │  config   │  ⚙️  Local config cache (.cache/)   │
│  📦 Section schemas              │           │  ⚙️  Graph API client               │
│  📦 Model routing                │           │  ⚙️  Gemini client                  │
│  📦 Version + signing            │           │  ⚙️  Azure Files storage IO         │
│  📦 License + customer registry  │           │                                      │
│                                  │           │                                      │
│  🖥️  Customer health dashboard   │ ◄── push──│  📈 Telemetry (no content)          │
│  💰 Billing                      │ telemetry │  📈 Errors (scrubbed)               │
│  🔔 Alerting                     │           │                                      │
│                                  │           │                                      │
│  Vendor IP, customer hidden ✅   │           │  Customer can read code — but only  │
│                                  │           │  the thin runtime, not the prompts  │
│                                  │           │  that drive it ✅                    │
└──────────────────────────────────┘         └──────────────────────────────────────┘
                                                          │
                                                          ▼
                                                    Customer M365
                                                    (mail, calendar,
                                                     OneDrive, Teams)
```

## 2. CP/DP protocol

- All CP/DP traffic is HTTPS; mTLS where feasible (Phase 5 of the
  rollout).
- Each customer's DP has a unique API key issued by the CP.
- Config bundles are JSON, signed by the CP's private key, verified
  by the DP using the embedded public key.
- Telemetry payloads are JSON, encrypted at rest in CP.

## 3. Trust model

The customer must trust:

- The vendor not to push a malicious prompt that exfiltrates data.
- The vendor's CP to keep operating reliably (or for the DP to
  function on cache long enough to weather outages).
- The vendor's CP-side security controls.

Mitigation tools (planned):

- **Bundle signing** — customer can cryptographically verify what
  was sent.
- **Audit feed** — customer can see all bundles pushed to their DP.
- **Bundle pinning** — customer can lock to a specific hash and skip
  auto-updates.

## 4. CP-side security

The CP is essentially a multi-tenant SaaS. Standard SaaS controls
apply:

- TLS in transit, AES at rest.
- Multi-tenant DB with row-level security (customer_id scoping on
  every query).
- HA: multiple instances + DB replication.
- Monitoring + alerting + oncall (required because all customers
  depend on it).

## 5. DP-side security

The DP is a stripped-down version of the BYOC deployment. All BYOC
controls apply (Azure encryption, mount path, atomic writes,
RBAC role, etc.).

Additional DP-specific requirements:

- Cache invalidation on bundle revocation.
- Fail-fast on signature verification failure.
- Continue on cache for up to 7 days when CP is unreachable.
- Refuse to start if the embedded CP public key is missing or
  doesn't match.

## 6. Bundle signing (Phase 5)

- CP holds the signing private key in Azure Key Vault.
- DP holds the public key embedded in the runtime image.
- Every bundle pushed to a DP is signed.
- DP rejects unsigned or invalid bundles.
- Customer can audit signing by checking the CP's logged signing
  operations against bundles their DP applied.

## 7. Threat model — what we defend against

All BYOC threats, plus:

- **Bundle tampering in transit**: signature verification.
- **Malicious vendor employee pushing harmful bundle**: signing log
  + customer audit feed + bundle pinning option.
- **CP / DP API key theft**: short-lived rotating tokens.
- **Cross-customer config leak in CP**: row-level security on DB.

## 8. Threat model — what we do NOT defend against (yet)

- **Vendor CP compromise**: a successful attack on the CP could
  push bundles to all customers. Customers who pin specific hashes
  are isolated.
- **Customer DP compromise via supply chain (image)**: same as
  BYOC.
- **Network adversary at sub-processor**: same as other tiers.

## 9. Sub-processor security posture

| Sub-processor | Relevant certifications |
|---|---|
| Microsoft Graph | Same as BYOC |
| Google Gemini | Same as BYOC |
| Our CP | SOC 2 (planned; required before enterprise launch) |
