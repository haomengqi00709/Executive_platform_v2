# Sub-processor List — CPDP tier (PLANNED)

**Effective date:** _TBD_
**Last updated:** _TBD_

> **This list reflects the planned CPDP tier. Tier not yet live.**

## Current sub-processors

| Sub-processor | Purpose | Data accessed | Location | Provider terms |
|---|---|---|---|---|
| **Microsoft Graph API** | OAuth + M365 access (data plane only) | Mail, calendar, OneDrive metadata + content you authorize, Teams chats | Customer's M365 tenant region | Microsoft Online Services DPA |
| **Google Gemini API** | AI processing (data plane initiates calls) | Email bodies, meeting recordings, document text (in-transit only) | United States | Google Cloud DPA |
| **CEO Platform Control Plane** | Sends config + prompts to your data plane; receives anonymized telemetry | Per-customer ID; telemetry metrics (counts, error rates); license verification pings. **Does NOT receive** customer content (mail, files, transcripts, etc.) | Vendor's SaaS (region TBD at CP launch) | Vendor's CP terms (TBD) |

## Why our CP is listed

Although the CP does not receive your data, it controls what the data
plane does with your data. Listing it as a sub-processor reflects this
control relationship for regulatory transparency.

## What flows over the CP/DP boundary

**CP → DP (config pushes):**
- AI prompts (text, signed bundles).
- Orchestration definitions (which modules to run when).
- Section schemas.
- Model routing instructions.
- License updates.

**DP → CP (telemetry pulls):**
- Customer ID + version reporting.
- Per-module run counts.
- Error counts (no error messages with PII).
- Health pings.

**Never crosses CP/DP boundary:**
- Email contents.
- Names or email addresses.
- File contents or names.
- Meeting transcripts.
- Anything else customer-identifiable.

## Bundle signing

CP → DP config bundles are cryptographically signed by us. Your DP
validates signatures before applying any configuration. You can pin a
specific signed bundle hash for additional protection if you don't
want auto-updates.

## How we update this list

30-day email notice before adding a new sub-processor or changing how
an existing one is used.

## Contact

**_TBD_**.
