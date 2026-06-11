# Privacy Policy — CPDP tier (PLANNED)

**Effective date:** _TBD — when CPDP tier launches_
**Last updated:** _TBD_

> **This policy describes the planned CPDP tier. The tier is not yet
> live; this document exists to clarify our intentions and will be
> finalized before launch.**

This Privacy Policy describes how the CEO AI Platform ("we", "us",
"the service") handles your information when the service is deployed
under the CPDP ("Control Plane / Data Plane") tier — a hybrid model
where the data-processing component runs in your own Azure
subscription and the orchestration / AI logic component runs in our
own SaaS.

## 1. What data we access

When you grant Microsoft 365 OAuth consent, the application reads:

- Email (inbox + sent), calendar, OneDrive files you've authorized,
  Teams chats with the Audrey bot, profile, and service usage data.

We do **not** collect or store passwords.

## 2. Where it's stored

Your **data** stays in your own Azure subscription, in the region you
chose at setup. Encrypted at rest with AES-256 (Azure default).

Our **control plane** ("CP"), which sends configuration and prompts to
your data plane ("DP"), runs in our own cloud. The control plane does
**not** receive your email content, calendar data, file content, or
any personally identifiable customer data.

The control plane receives only:

- A per-customer identifier (so we know which customer is asking for
  configuration).
- Anonymized telemetry (e.g., "this data plane ran the email module
  12 times in the last hour, with 0 errors").
- License validation pings.

## 3. Who else sees it

The full sub-processor list is in
[subprocessor-list.md](./subprocessor-list.md). Summary:

- **Microsoft Graph API** — reads your M365 data via your OAuth grant.
- **Google Gemini API** — processes text, audio, video for AI
  features.
- **Our own control plane** — sends configuration and prompts to your
  data plane; receives anonymized telemetry.

The third bullet is the new sub-processor introduced by the CPDP tier
(not present in SaaS or BYOC). It is listed as a sub-processor
because its actions affect what happens to your data (it tells the
data plane which prompts to send to Gemini, etc.).

## 4. How long we keep it

- **Customer data in your Azure**: under your control.
- **CP-side customer record**: kept while your subscription is active.
  Deleted within 30 days of contract termination.
- **CP-side telemetry**: aggregated and anonymized within 90 days;
  per-customer records purged at termination.

## 5. Vendor (human) access

Same protocol as BYOC: vendor uses an RBAC role you granted, can be
revoked any time, all actions logged in your Activity Log.

For the CP side: vendor employees with operational access to our CP
infrastructure follow our internal access control policy (_to be
finalized at launch_).

## 6. Your rights

- **Access**: data is in your Azure (you have direct access).
- **Export**: same as BYOC.
- **Delete**: delete your Azure resource group + send us a termination
  request to delete CP-side records.
- **Revoke** Microsoft OAuth at
  https://myaccount.microsoft.com → Permissions.
- **Audit** what we send your data plane: we provide a feed of all
  prompts / config pushed to your DP, signed for tamper-evidence.
- **Pin a specific bundle hash**: prevent auto-updates from CP.

## 7. Cookies

A single HTTP-only, Secure session cookie. No tracking cookies.

## 8. Children's privacy

Not for children under 16.

## 9. Changes to this policy

We will notify at least 14 days before any material change.

## 10. Contact

**_TBD — partner or Jason contact email_**.
