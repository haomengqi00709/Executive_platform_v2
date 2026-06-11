# How we handle your data — the short version (BYOC)

**For:** prospective and current BYOC customers.

## The short story

Your data lives in **your Azure subscription**, in the region you
chose. We don't have a copy anywhere else.

## What we read

With your Microsoft 365 OAuth consent, the application reads:

- Your **Outlook email** (inbox + sent).
- Your **calendar** (events, attendees, metadata).
- **OneDrive files** you've authorized.
- Your 1:1 **Teams chat** with the Audrey assistant bot.

We never see your Microsoft password.

## What the application does with it

Five AI assistant modules:

1. **Daily briefing** — calendar + email summary delivered every
   morning.
2. **Email triage** — sorts, prioritizes, drafts replies.
3. **Meeting summary** — transcribes recordings and extracts action
   items.
4. **Relationship intelligence** — surfaces talk patterns.
5. **Expenses** — finds receipts and invoices.

## Where your data lives

- Application: **your** Azure App Service.
- Data at rest: **your** Azure Files share, AES-256 encrypted by Azure.
- Region: **you chose** at setup.

## Who else touches it

Two sub-processors (full list in
[subprocessor-list.md](./subprocessor-list.md)):

- **Microsoft** — you're already using them for M365.
- **Google Gemini** — for AI processing. Per Gemini's paid API terms,
  your content is not retained for model training.

Note: Railway is **not** used for BYOC. There is no shared
infrastructure between you and other customers.

## Vendor (us) access

During normal operation, we don't touch your data. When debugging is
required, we use the RBAC role you granted us — and you can revoke it
at any time. All vendor actions appear in your Azure Activity Log.

## What you control

- **Stop everything**: delete the Azure resource group hosting the
  platform. All data is gone immediately.
- **Revoke vendor access**: Azure portal → Access control (IAM) →
  remove our service principal.
- **Revoke OAuth**: https://myaccount.microsoft.com → Permissions.
- **Turn off individual modules**: Settings page in the app.

## Want more detail?

- Full [Privacy Policy](./privacy-policy.md)
- Full [Sub-processor List](./subprocessor-list.md)
- Service [Terms of Service](./terms-of-service.md)

Email **_TBD — contact_** with any question.
