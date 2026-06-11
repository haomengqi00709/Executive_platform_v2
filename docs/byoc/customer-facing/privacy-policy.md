# Privacy Policy — BYOC tier

**Effective date:** _TBD — set on contract signing_
**Last updated:** _TBD_

This Privacy Policy describes how the CEO AI Platform ("we", "us", "the
service") handles your information when the service is deployed in your
own Azure subscription under the BYOC ("Bring Your Own Cloud") tier.

This is a beta-stage product. The policy below describes our current
practices honestly; it has not yet been reviewed by external counsel.

## 1. What data we access

When you grant Microsoft 365 OAuth consent, the service accesses:

- **Email**: messages in your Outlook inbox and sent folder.
- **Calendar**: events and meeting metadata.
- **OneDrive files**: files you've authorized for reading.
- **Microsoft Teams chats**: messages with the "Audrey" assistant bot.
- **Profile**: your name, email address, profile photo from Microsoft.
- **Service usage data**: logs of feature usage, errors, timings.

We do **not** collect or store passwords. Authentication is handled
entirely by Microsoft via OAuth 2.0.

## 2. Why we collect it

To deliver the five AI assistant modules: daily briefing, email triage,
meeting summarization, relationship intelligence, expense capture.

We do not use your data to train AI models, sell to advertisers, or
share with anyone outside the sub-processors listed in
[subprocessor-list.md](./subprocessor-list.md).

## 3. Where it's stored

**This is the BYOC tier — your data lives in your own Azure
subscription.** Specifically:

- **At rest**: Azure Files share in your storage account, in the Azure
  region you chose at setup. Encrypted with AES-256 (Azure default,
  managed by Microsoft).
- **In transit**: TLS 1.3 within Azure and to all external APIs.

We do not have a copy of your data anywhere else. If you delete the
Azure resource group that hosts the service, your data is gone — both
from the live system and from any backups you've configured.

## 4. Who else sees it

The full sub-processor list is in
[subprocessor-list.md](./subprocessor-list.md). Summary:

- **Microsoft Graph API** — reads your M365 data via your OAuth grant.
- **Google Gemini API** — processes text, audio, video for AI features.

Unlike the SaaS tier, Railway is **not** a sub-processor here. The
infrastructure your service runs on is your own Azure subscription.

We will notify you at least 30 days before adding a new sub-processor.

## 5. How long we keep it

- **Active accounts**: your data lives in your Azure as long as your
  service is running. You control retention.
- **Account deletion / service termination**: see Section 7.

## 6. Vendor (human) access

Under normal operation, we (the vendor) do not access your data. When
debugging is required:

- We will request access ahead of time via email (target: 24h notice,
  except in emergencies).
- We use the RBAC role you granted us in your Azure subscription —
  typically Contributor scoped to the platform's resource group, or a
  custom role with narrower permissions.
- All vendor access actions are logged in your Azure Activity Log —
  visible to you in the Azure portal.
- You may revoke our RBAC role at any time. We lose access immediately.

## 7. Your rights

You may, at any time:

- **Access** your data directly in your Azure storage account.
- **Export** your data — it's already in your storage account; we can
  provide a script to assemble it as a tarball.
- **Delete** by removing the platform's Azure resource group, which
  cascades to all data. Optionally also request that we delete
  vendor-side artifacts (see Section 7.1).
- **Revoke** Microsoft OAuth consent at
  https://myaccount.microsoft.com → Permissions.
- **Revoke** our vendor RBAC role in Azure → Access control (IAM).

### 7.1 Vendor-side artifacts to delete

Even though your data lives in your Azure, we maintain a small number
of artifacts on our side that we delete on service termination:

- The container image we built and pushed to your ACR.
- GitHub Actions secrets we used to deploy.
- The service principal we use to access your subscription.
- Any temporary OAuth tokens cached during operations.

We will provide a deletion certificate confirming this within 7 days of
request.

## 8. Cookies

A single HTTP-only, Secure session cookie. No tracking or analytics
cookies.

## 9. Children's privacy

The service is not directed at children under 16. We do not knowingly
collect data from anyone under 16.

## 10. Changes to this policy

We will notify you by email at least 14 days before any material
change.

## 11. Contact

For privacy questions: **_TBD — partner or Jason contact email_**.
