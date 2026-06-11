---
title: "CEO AI Platform"
subtitle: "Customer Information Brief"
date: "Version 1.0 — [DATE]"
---

> A practical overview of what the CEO AI Platform does, how we handle your data, the deployment options available to you, and the controls you retain at all times. Intended to be read during your evaluation. This brief is not a legal agreement; the binding contract between you and us is your separately signed Service Agreement.

# 1. About the Service

The CEO AI Platform is an AI assistant for executives that connects to your Microsoft 365 environment and helps you handle the day-to-day. It runs five modules:

1. **Daily Briefing** — every morning, a short summary of your calendar, the emails that matter, and relevant news.
2. **Email Triage** — your inbox sorted, prioritized, with draft replies ready for your review and approval.
3. **Meeting Summary** — meeting recordings transcribed automatically, with key decisions and action items extracted.
4. **Relationship Intelligence** — surfaces who you've been actively talking to and who's gone quiet.
5. **Expenses** — receipts and invoices identified from your inbox and OneDrive, with vendor and amount extracted.

Output is delivered to a web dashboard and to Microsoft Teams via an assistant bot named Audrey, which we provision for you.

The product is in beta. It is built and supported by a small team focused on getting it right for a small group of executive users before broad release.

# 2. Data We Process

When you authorize the Service with your Microsoft 365 account, we access:

- **Email** — Outlook inbox and sent folder.
- **Calendar** — events, attendees, meeting metadata.
- **OneDrive files** — files you've authorized for access, primarily meeting recordings.
- **Microsoft Teams** — your 1:1 chat with the Audrey assistant bot.
- **Profile** — your name, email address, and profile photograph from Microsoft.

We use this data only to run the five modules described in Section 1.

## What we will not do

We do not:

- Use your data to train artificial intelligence models.
- Sell your data, or share it with advertisers or marketers.
- Share your data with anyone outside the sub-processors listed in Section 3.
- Read your data for any purpose other than running the modules — see Section 4 for our vendor-access policy.

# 3. Sub-processors

To deliver the Service we use three third-party providers. We share the minimum data necessary with each, under written agreements that impose security and confidentiality obligations.

| Provider | Role | What it sees | Location |
|---|---|---|---|
| **Microsoft** (Graph API) | Authentication and access to your M365 data | Whatever you authorize via OAuth | Your M365 tenant region |
| **Google Gemini API** | Generative AI processing of text, audio, video | Email, file, and audio content — **in transit only**. Under Google's paid API terms, content is not retained for model training. | United States |
| **Railway** (SaaS tier only) | Application hosting | Your data at rest | US-east region |

We will give you at least 30 days' notice before adding any new sub-processor.

**For the BYOC and CPDP deployment tiers (Section 5), Railway is not involved.** Your data lives in your own Microsoft Azure subscription. The only sub-processors that touch your data are Microsoft and Google Gemini.

# 4. Our Security Commitment

## How we protect your data

- **In transit**: TLS 1.3 encryption end to end.
- **At rest**: AES-256 encryption.
- **Per-account isolation**: structurally enforced by the application. Cross-account access is not possible through the API.
- **Authentication**: Microsoft OAuth only. We never see or store your password.

## How we treat your data

We do not routinely read your data. The application processes it automatically; humans on our team do not.

When debugging is required — for example, to investigate a bug you have reported — our access follows this protocol:

- We give you at least **24 hours' advance notice** for routine debugging access, except in emergencies. Emergency access is disclosed to you within 24 hours after the fact.
- We use only the minimum access needed to reproduce or diagnose the issue.
- All access is logged.
- For the **BYOC and CPDP tiers**, where the platform runs in your own Azure subscription, every action is recorded in your Azure Activity Log, and you can revoke our access at any moment by removing the role assignment.
- For the **SaaS tier**, we record our access internally and will share that record on request.

## Logs

We retain service logs for **30 days**. Personally identifying information is automatically redacted (email addresses, names, file content). These logs are used only to:

- Diagnose errors and improve reliability.
- Understand usage patterns to inform feature development and customization.

We do not use log data for advertising, sale, or external sharing.

## If something goes wrong

If we discover a security incident affecting your account, we will notify you within **72 hours** of confirming the incident. The notice will describe what happened, what data was affected, what we have done, and what (if anything) you should do.

# 5. Deployment Options

Three deployment options are available, designed for different data-residency and operational preferences.

| | **SaaS** | **BYOC** | **CPDP (Planned)** |
|---|---|---|---|
| Where your data lives | Our infrastructure (Railway, US-east) | Your own Azure subscription | Your own Azure subscription |
| Where the AI prompts live | In the deployed application image | In the deployed application image | In our hosted control plane (not visible to you) |
| Onboarding time | Minutes — sign in with Microsoft | 1–2 weeks — Azure setup plus legal | 1–2 weeks plus control-plane registration |
| Status | Available now | Available now | Planned, not yet available |
| Best for | Trials; smaller executives; data residency not a hard requirement | A single CEO or executive whose data must stay in the customer's own cloud | Larger customers requiring both data residency and protection of the vendor's AI intellectual property |

## SaaS Tier

You sign in with your Microsoft 365 account on our hosted platform. Your data is stored in Railway's US-east region under AES-256 encryption. The platform is shared infrastructure, with strict per-account isolation. Suitable for fast onboarding, trials, and customers who are comfortable with their data residing on our infrastructure.

## BYOC Tier (Bring Your Own Cloud)

The Service is deployed into your own Microsoft Azure subscription. Your data lives in your Azure Files storage account, in the Azure region you choose. We never hold a copy of your data outside your Azure subscription. Our access to your subscription is via a Role-Based Access Control role you grant — and which you can revoke at any time.

A signed Master Services Agreement, Non-Disclosure Agreement, IP Assignment, and Data Processing Agreement is required before the BYOC tier is deployed.

## CPDP Tier (Control Plane / Data Plane) — Planned

A hybrid that combines BYOC-style data residency with vendor-protected AI prompts. Your **data plane** runs in your Azure (like BYOC). Our **control plane**, in our own cloud, holds the AI prompts and orchestration configuration, signs each bundle cryptographically, and pushes it to your data plane.

- Your data never leaves your Azure.
- Our prompts never enter your cloud as visible source code.
- You can audit every bundle the control plane has sent to your data plane.
- You can pin a specific bundle hash to prevent automatic updates.

The CPDP tier is not yet available. Estimated availability is late 2026.

# 6. Your Controls

You retain control of your data and your relationship with us at all times.

## Across all tiers

- **Disable individual modules** in the Service settings.
- **Revoke Microsoft OAuth consent** at https://myaccount.microsoft.com → Permissions. The Service immediately loses access to your M365 data.

## SaaS tier specifically

- **Delete your account** from the Service settings. Your data is removed from production within 7 days and from backups within 30 days.
- **Export your data** as a JSON archive on request.

## BYOC tier specifically

- **Revoke vendor access** in Azure → Access control (IAM). We lose access immediately.
- **Delete the deployment** by removing the platform's resource group in Azure. All your data is removed in the same operation.
- **Request a Deletion Certificate** confirming we have deleted vendor-side artifacts (the container image, deployment secrets, and service principal credentials) within 7 days of your termination request.

## CPDP tier specifically (when available)

- All BYOC controls above, plus:
- **Cancel your control-plane API key**. Your data plane continues operating on its cached configuration for up to 7 days, then stops.
- **Pin a specific configuration bundle hash** to prevent automatic updates from our control plane.

# 7. Standard Privacy Items

## Data retention

While your account is active, we retain your data to deliver the Service.

When your account is deleted:

- Data is removed from production within **7 days**.
- Data is removed from backups within **30 days**.
- Service logs (with PII redacted) are retained for **30 days** from generation.

For the BYOC and CPDP tiers, retention is fully under your control in your own Azure subscription.

## Cookies

A single HTTP-only, Secure session cookie is used to keep you signed in. No tracking, advertising, or analytics cookies are used.

## Age

The Service is not directed to anyone under 16 years of age.

## Updates to this document

We will notify you by email at least **14 days** before any material change to how we handle your data.

---

*This document is a beta-stage product information brief. The binding contractual document between you and us is your separately signed Service Agreement, which prevails in the event of any conflict. This brief has not been reviewed by external legal counsel; a formal legal review will be performed prior to commercial general availability.*
