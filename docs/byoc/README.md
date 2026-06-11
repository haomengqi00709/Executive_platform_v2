# BYOC deployment docs

Documentation for the BYOC tier — single-tenant deployments where each
customer runs the platform inside their own Azure subscription. See
`docs/saas/` for the multi-tenant SaaS tier and `docs/cpdp/` for the
hybrid Control plane / Data plane tier.

## Folder layout

Scope is **security + privacy + deployment**. Other operational docs
(terms of service, incident response, backup/recovery, retention
policy) are intentionally not in this folder yet — they describe
formal processes that aren't fully implemented. They will be added
when the corresponding features land.

### `customer-facing/` — privacy

- **privacy-policy.md** — public privacy policy (BYOC-specific)
- **subprocessor-list.md** — third parties that touch customer data
  (Railway is NOT a sub-processor for BYOC — the customer's Azure is
  theirs)
- **data-handling-summary.md** — 1-page customer-friendly summary

### `internal/` — security

- **security-overview.md** — architecture + controls + threat model

### `operations/` — deployment

- **deployment-runbook.md** — Azure App Service, ACR, Azure Files
  ongoing operations
- **customer-onboarding.md** — full new-customer setup (the largest
  doc; partner + Jason both reference this for each new deal)

## Key differences from SaaS

| Aspect | SaaS | BYOC |
|---|---|---|
| Where data lives | Railway US-east | Customer's Azure tenant (customer choice of region) |
| Who owns infra | Us | Customer |
| Who pays Azure / Railway bill | Us | Customer |
| Vendor access | Application-level (we host) | RBAC role granted by customer; revocable any time |
| Sub-processors | Microsoft, Gemini, Railway | Microsoft, Gemini |
| Audit log | Limited (application logs only) | Native (Azure Activity Log) |
| Compliance posture | What we have | What customer's Azure provides + what we have |
| Onboarding time | Minutes | 1-2 weeks (including legal) |
| Onboarding complexity | One env var update | Full Azure resource setup |

## Reference

- `docs/deployment-mode-3-byoc.md` — architectural deep-dive and
  decision framework. Read this before reading anything in this folder.
- `docs/security-deployment-checklist.md` — BYOC-specific gap analysis.
- `docs/partner-sales-brief.md` — BYOC tier in partner sales context.

## Status (beta + 1 paying customer reference: IPS)

These docs reflect the IPS deployment as the canonical reference. They
are clear, thorough, and honest, but have not been reviewed by external
counsel. The commercial artifacts (MSA, NDA, IP Assignment, DPA) must
be drafted by a lawyer before the second paid BYOC deployment.
