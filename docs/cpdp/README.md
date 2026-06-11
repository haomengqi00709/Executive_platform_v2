# CPDP (Control plane / Data plane) deployment docs

Documentation for the future CPDP tier — a hybrid architecture where
the **data plane** runs in the customer's Azure subscription (like
BYOC) but the **control plane** (prompts, orchestration, license,
telemetry) runs in our own SaaS.

See `docs/saas/` for the SaaS tier and `docs/byoc/` for the BYOC tier.

## Status: planned, not yet built

**The CPDP tier does not exist in code as of June 2026.** This folder
documents the planned architecture and how privacy / security /
deployment will look once it's built.

Implementation is gated on:

1. At least 5 paying BYOC customers.
2. At least one customer requiring the IP isolation CPDP provides.
3. ~1-2 months of focused engineering once kicked off.

When the code exists, every doc in this folder will be revised based
on what was actually built (not the architectural vision).

## Folder layout (mirrors `byoc/`)

Scope is **security + privacy + deployment**. Other operational docs
(terms of service, incident response, backup, retention) are not
included — they describe processes that don't exist yet (the whole
CPDP tier doesn't exist yet).

### `customer-facing/` — privacy
- **privacy-policy.md** — customer data in their Azure; our CP is a
  sub-processor.
- **subprocessor-list.md** — Microsoft, Gemini, **our own CP**.
- **data-handling-summary.md** — 1-page summary.

### `internal/` — security
- **security-overview.md** — CP architecture + DP architecture +
  cross-plane protocol + threat model.

### `operations/` — deployment
- **deployment-runbook.md** — deploying CP + deploying each DP.
- **customer-onboarding.md** — onboarding a CPDP customer.

## Key differences from SaaS and BYOC

| Aspect | SaaS | BYOC | CPDP |
|---|---|---|---|
| Data location | Our Railway | Customer Azure | Customer Azure |
| Prompts / IP location | Customer-visible (in image) | Customer-visible (in image) | **Our CP — hidden** |
| Sub-processors | MS + Gemini + Railway | MS + Gemini | MS + Gemini + **Our CP** |
| Customer trust requirement | Trust our hosting | Trust our access control | Trust our config push |
| Single point of failure | Railway | Customer's Azure | Our CP (DP cache buffers 7 days) |
| Vendor IP exposure | Full source visible in image | Full source visible in image | Only thin runtime visible; prompts hidden |
| Onboarding complexity | Minutes | 1-2 weeks | 1-2 weeks + CP registration |

## Reference

- `docs/deployment-mode-4-control-data-plane.md` — architectural
  vision and migration path from BYOC.
- `docs/security-deployment-checklist.md` — CPDP-specific gaps
  (mostly "everything").
- `docs/partner-sales-brief.md` — CPDP pitch context (currently:
  "don't sell yet").

## Why these docs exist before the code

Writing the legal / privacy / security artifacts before the code
helps:

1. Clarify exactly what we're going to build.
2. Identify trust and security requirements early.
3. Give the partner a clear roadmap story for prospects who ask about
   future capabilities.
4. Surface decisions (sub-processor disclosure, signing requirements)
   that affect the architecture, not the other way around.

These docs will be revised when the code lands.
