# How we handle your data — CPDP tier (PLANNED)

**For:** customers evaluating the CPDP tier.

> **Note: This tier is not yet live. Document reflects planned behavior.**

## The short story

Your data lives in **your Azure**. Our hosted control plane sends
prompts and configuration to your data plane — but never receives
your data.

## What we read

With your Microsoft 365 OAuth consent, the data plane in your Azure
reads:

- Outlook email (inbox + sent).
- Calendar.
- OneDrive files you've authorized.
- Teams chats with the Audrey assistant bot.

## What the application does

Five AI assistant modules (same as other tiers): briefing, email
triage, meeting summary, relationship intelligence, expense capture.

## Where your data lives

- **Application logic + data**: your Azure App Service + Azure Files
  share.
- **AI prompts + orchestration**: our hosted control plane (you don't
  see them; they are vendor IP).

## What crosses the CP/DP boundary

- **CP → DP**: AI prompts, configuration, license updates. Signed
  for integrity.
- **DP → CP**: anonymized telemetry (counts, error rates). **No
  customer data.**

## Who else touches it

Three sub-processors (full list in
[subprocessor-list.md](./subprocessor-list.md)):

- **Microsoft** — your M365 provider.
- **Google Gemini** — AI processing (DP initiates calls; CP not
  involved).
- **Our control plane** — sends config; receives telemetry.

## What you control

- **Delete your Azure resource group**: data is gone.
- **Revoke our RBAC on Azure**: we lose access.
- **Revoke Microsoft OAuth**: app can't access M365.
- **Cancel CP API key**: DP can't pull new config (continues on
  cache for 7 days).
- **Pin a specific config bundle hash**: prevent auto-updates from
  CP.

## Want more detail?

- Full [Privacy Policy](./privacy-policy.md)
- Full [Sub-processor List](./subprocessor-list.md)

Email **_TBD — contact_**.
