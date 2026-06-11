# Privacy Policy

**Effective date:** _TBD — set on launch_
**Last updated:** _TBD_

This Privacy Policy describes how the CEO AI Platform ("we", "us", "the
service") handles your information when you use the SaaS-hosted version of
the product.

This is a beta-stage product. The policy below describes our current
practices honestly; it has not yet been reviewed by external counsel.

## 1. What data we collect

When you sign in with your Microsoft 365 account and grant consent, the
service accesses:

- **Email**: messages in your Outlook inbox and sent folder.
- **Calendar**: events and meeting metadata.
- **OneDrive files**: files you've authorized for reading (primarily
  meeting recordings).
- **Microsoft Teams chats**: messages with the "Audrey" assistant bot we
  provision for you, including 1:1 chat history with that bot.
- **Profile**: your name, email address, and profile photo from Microsoft.
- **Service usage data**: logs of which features you use, error events,
  and basic timing metrics. These do not include the content of your
  messages.

We do **not** collect or store passwords. Authentication is handled
entirely by Microsoft via OAuth 2.0.

## 2. Why we collect it

All collected data is used solely to power the five AI assistant modules:

1. Daily executive briefing (calendar + email summary).
2. Email triage and draft reply generation.
3. Meeting recording transcription and summary.
4. Relationship intelligence (email frequency patterns).
5. Expense and receipt capture.

We do not use your data to train AI models, sell to advertisers, or share
with anyone outside the sub-processors listed in
[subprocessor-list.md](./subprocessor-list.md).

## 3. How we process and protect it

- **In transit**: all data moves over TLS 1.3.
- **At rest**: stored on Railway with AES-256 encryption (provider default).
- **Isolation**: each user's data lives in a separate filesystem path. The
  application code only constructs that path from the authenticated
  session, never from a request parameter — so cross-user access is not
  possible via the API.
- **Access**: only the service's automated processes read your data during
  normal operation. Human (vendor) access happens only when you report a
  problem that requires debugging. See our internal security overview for
  details (available on request).

## 4. Where it's stored

The SaaS tier runs on Railway in the US-east region. If you require data
residency in a specific region (EU, Canada, etc.), the BYOC tier may be a
better fit — contact your sales partner.

## 5. Who else sees it

We share the minimum data necessary with three sub-processors. The complete
list, with purpose and data details, is in
[subprocessor-list.md](./subprocessor-list.md).

Summary:

- **Microsoft Graph API** — reads your M365 data via your OAuth grant.
- **Google Gemini API** — processes text, audio, and video for AI features.
- **Railway** — hosts the application and your stored data.

We will notify you at least 30 days before adding a new sub-processor.

## 6. How long we keep it

- **Active accounts**: we keep your data for as long as your account is
  active.
- **Account deletion**: when you click "Delete my account" in Settings (or
  email us at the address below), your data is removed from production
  storage within 7 days. Surviving copies in backups are purged within 30
  days.
- **Service logs**: retained 30 days.

## 7. Your rights

You may, at any time:

- **Access** your data via the dashboard or by email request.
- **Export** your data as a JSON archive (currently handled on request;
  self-service export is on the roadmap).
- **Delete** your account via Settings → "Delete my account".
- **Revoke** Microsoft OAuth consent at
  https://myaccount.microsoft.com/security-info → Permissions.
- **Restrict** any specific module by disabling it in Settings.

## 8. Cookies

We use a single HTTP-only, Secure session cookie to keep you signed in. No
tracking or analytics cookies are used in the beta.

## 9. Children's privacy

The service is not directed at children under 16. We do not knowingly
collect data from anyone under 16.

## 10. Changes to this policy

We will notify you by email at least 14 days before any material change.

## 11. Contact

For privacy questions, data requests, or to report a concern, email
**_TBD — partner or Jason contact email_**.
