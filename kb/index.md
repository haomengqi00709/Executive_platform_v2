# KB Index

The catalog of the code knowledge base. Each page describes a capability or a
cross-cutting system concern. Conventions live in [KB_GUIDE](KB_GUIDE.md).

> Volatile facts are NOT in these pages: for the **exact current prompt** of a
> section, read `src/skills/{id}/skill.md` live; for **known issues / open
> requests**, read the feedback-board's request list.

## Capabilities
- [Daily Briefing & Recap](capabilities/briefing.md) — `ai_summary` morning brief + `yesterday_recap`.
- [Email Triage](capabilities/email-triage.md) — `reply_needed`, `followup_needed`, the screener, draft replies.
- [Commitments Tracking](capabilities/commitments.md) — `commitments_extract`, `upcoming_commitments`, `due_today` + lifecycle.
- [Meeting Intelligence](capabilities/meetings.md) — `meetings_today`, `meeting_prep`, recordings → summaries/actions, the Meeting DB.
- [Project Tracking](capabilities/projects.md) — `project_status`, `projects_needing_attention`.
- [Relationship Health](capabilities/relationships.md) — contact-frequency health + cooling signals.
- [Market & Business Intelligence](capabilities/intelligence.md) — `market_intelligence`, `company_intelligence`, `business_insights`.
- [Document Capture (Expenses)](capabilities/expenses.md) — receipts/invoices/contracts; receipts → Excel.
- [Data Management](capabilities/data-management.md) — CRM, Projects, Companies, Cleanup, bulk import/merge.
- [Workflow Tools](capabilities/workflow-tools.md) — Outreach, Draft Composer; drafts never auto-sent.
- [Delivery & Push Orchestration](capabilities/delivery.md) — Dashboard / Teams / Drafts channels, scheduled briefings, email monitor.

## Architecture
- [System Overview](architecture/overview.md) — stack, data flow, the 5 core principles.
- [How a Section Works](architecture/sections-framework.md) — skill.md / validator / instruction layers; the screener.
- [Data Layout & Auth](architecture/data-and-auth.md) — MSAL OAuth, Graph, `.data/{uid}/` layout.
- [Deployment](architecture/deployment.md) — single `main`, Railway + Azure; sibling services.
