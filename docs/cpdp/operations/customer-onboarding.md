# Customer onboarding — CPDP tier (PLANNED)

**Audience:** Jason + partner.

> **Describes planned procedure. CPDP not yet live.**

CPDP onboarding is **BYOC + CP-side registration**.

## 1. Prerequisites

Same as BYOC (`docs/byoc/operations/customer-onboarding.md`
Section 1), plus:

- Customer agrees to CP/DP architecture (review the privacy /
  sub-processor list together).
- Customer agrees on bundle update policy (auto-update vs pinned).

## 2. CP-side setup (vendor)

Before doing the Azure work:

1. Vendor admin opens CP dashboard.
2. Create customer record:
   - Name, contact, billing.
   - Generate per-customer API key.
   - Set bundle update policy (auto / pinned).
3. Provide customer with:
   - CP API key (treat as a secret; goes into DP env vars).
   - CP URL.
   - List of bundle versions available (so customer can pick a
     starting pin if desired).

## 3. DP-side setup (customer Azure)

Mostly the same as BYOC
(`docs/byoc/operations/customer-onboarding.md` Sections 2-3).

Differences:

- The container image deployed to customer's ACR is the **DP image**
  (slim, no prompts), not the full BYOC image.
- Additional env vars:
  - `CP_URL` = our CP endpoint.
  - `CP_API_KEY` = generated in step 2.3.
  - `PINNED_BUNDLE_HASH` = if customer wants to pin.

## 4. Verification

In addition to BYOC verification:

- DP successfully pulls a config bundle from CP at startup.
- Signing verification passes.
- Telemetry ping appears in CP dashboard within 1 minute.
- Test config push: change a prompt in CP, force DP refresh, verify
  new prompt is applied.

## 5. Handover documentation

In addition to BYOC handover:

- CP customer dashboard URL + login.
- Bundle audit feed access (where to see what's been pushed).
- Pinning instructions if customer wants to control updates.

## 6. Ongoing operations

- Vendor pushes prompt updates via CP (no per-customer deploy
  needed for prompt changes — this is the whole point of CPDP).
- Vendor pushes DP runtime updates per BYOC procedure (when DP
  image changes).
- Customer monitors CP dashboard for telemetry.

## 7. Estimated timeline

- CP customer registration: 30 minutes.
- DP Azure setup: same as BYOC (1 working day).
- Total: same as BYOC + 30 minutes.
