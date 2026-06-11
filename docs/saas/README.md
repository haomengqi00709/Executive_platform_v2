# SaaS deployment docs

Documentation for the SaaS tier — the multi-tenant deployment hosted on
Railway, used by partner-invited beta users. See [docs/byoc/](../byoc/) and
[docs/cpdp/](../cpdp/) for the other two tiers.

## Folder layout

### `customer-facing/`
Published or shared with end users. Tone is plain-English and beta-friendly.
Treat these as the legal/privacy artifacts of the product.

- **privacy-policy.md** — public privacy policy
- **terms-of-service.md** — terms of use
- **subprocessor-list.md** — third parties that touch customer data
- **data-handling-summary.md** — 1-page CEO-friendly version of the above

### `internal/`
Operational SOPs. Not published, but may be shared with a customer's security
team on request.

- **security-overview.md** — architecture + controls + threat model
- **incident-response-plan.md** — how we handle breaches and outages
- **backup-and-recovery.md** — what we back up and how to restore
- **data-retention-deletion.md** — how long we keep things, how we delete

### `operations/`
Runbooks for Jason and the sales partner. Never shared externally.

- **deployment-runbook.md** — Railway setup, env vars, deploy flow
- **customer-onboarding.md** — partner workflow for adding new beta users

## How to use this folder

- **Partner before a sales call**: read `customer-facing/data-handling-summary.md` and `customer-facing/subprocessor-list.md`.
- **Customer asks about security**: send `customer-facing/` files; offer `internal/security-overview.md` on request.
- **New beta invite**: follow `operations/customer-onboarding.md`.
- **Production incident**: follow `internal/incident-response-plan.md`.

## Status (beta)

These docs are written for the beta launch. They are clear, thorough, and
honest, but have **not** been reviewed by external counsel. Before charging
paying customers — or signing with any customer that has its own legal
review — engage a lawyer to do a pass over the `customer-facing/` files.
