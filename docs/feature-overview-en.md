---
title: "Executive Assistant"
subtitle: "Feature Overview"
date: "Version 1.0"
---

> This document provides an overview of the Executive Assistant's current product capabilities, organized by user interaction model into three categories. Its purpose is to give the reader a complete and objective understanding of what the platform does.

---

# 1. Product Overview

Executive Assistant is an AI assistant designed for executives. It connects to the user's Microsoft 365 environment (Outlook, Calendar, OneDrive, and Teams) and provides three categories of capability around an executive's daily workflow:

- **Proactive intelligence delivery** — the AI analyzes data and delivers daily insights without manual triggering.
- **Structured data management** — users maintain their business records inside the platform (contacts, projects, companies).
- **On-demand workflows** — users trigger specific AI-powered tasks when needed.

Output is delivered through two channels: a web dashboard and Microsoft Teams (via a dedicated AI assistant bot provisioned for the user).

---

# 2. Categories

The platform's features are organized by user interaction model into three categories:

| Category | Description | Interaction Model |
|---|---|---|
| **Category 1 — Intelligence Delivery** | AI proactively computes and pushes insights | "I open the app and see what the AI has prepared" |
| **Category 2 — Data Management** | User maintains structured business records | "I manage my business data" |
| **Category 3 — Workflow Tools** | User triggers specific AI-powered tasks | "I ask the AI to complete a specific task for me" |

---

# 3. Category 1 — Intelligence Delivery

The AI proactively analyzes data and delivers results. This category includes 18 intelligence sections, a delivery orchestration layer, and two output channels.

## 3.1 Intelligence Sections (18 total, organized into 7 groups)

| Group | Section | Content |
|---|---|---|
| **Briefing** | AI Morning Summary | Daily morning summary: today's calendar, emails worth replying to, key relationships, relevant industry updates |
| **Email** | Reply Needed | Inbox messages awaiting a reply, prioritized, with reason and suggested opening line |
| | Followup Needed | Sent messages that have not received a response, with days waiting and suggested follow-up tone |
| | Commitments Extract | Commitments extracted from emails: who promised what, when |
| | Upcoming Commitments | Commitments due within the next 7 days |
| | Due Today | Commitments and to-dos due today |
| | Yesterday Recap | Yesterday's activity: emails sent and received, meetings, new commitments |
| **Meetings** | Meetings Today | Today's calendar, with attendees and meeting join links |
| | Recent Meetings | Recent meeting summaries, decisions, and action items (from recording transcription) |
| | Meeting Action Items | All to-do items aggregated across meetings |
| **Projects** | Projects Needing Attention | Projects with abnormal status (stalled, needs attention, new phase) |
| | Project Status | Portfolio view of all projects (status, momentum, recent activity, next step) |
| **Intelligence** | Relationship Health | Key contacts' relationship health: contact frequency, cooling signals, suggested actions |
| | Market Intelligence | Industry signals (regulation, funding, M&A, technology shifts), retrieved via Google Search |
| | Company Intelligence | News on specific companies flagged for monitoring |
| **Insights** | Business Insights | Weekly business summary: trends, statistics, highlights |
| **Documents** | Expenses | Identified receipts, invoices, and contracts |

## 3.2 Delivery Orchestration

Users can configure how the AI delivers content:

| Feature | Description |
|---|---|
| **Scheduled Briefings** | Users configure cron schedules, section bundles, and delivery channels. Each user can create multiple independent briefings (e.g., "weekdays 7 a.m.: deliver AI Summary + Due Today + Meetings Today"). |
| **Email Monitor** | New emails are pushed to Teams in real time, without waiting for the scheduled briefing. Configurable working-hours window, digest interval, and "priority-first" option. |
| **Meeting Autoresponder** | When new meeting recordings appear in OneDrive, the autoresponder automatically generates a summary, pushes it to Teams, and drafts a follow-up email in Outlook Drafts. |
| **Per-section Instructions** | Each section accepts a custom free-text instruction to guide AI behavior (e.g., "exclude marketing emails from Reply Needed"). |

## 3.3 Output Channels

| Content | Channel |
|---|---|
| All 18 sections | Web dashboard (detail pages with full lists and inline actions) |
| Sections selected in a briefing | Microsoft Teams (pushed on schedule) |
| Email Monitor matches | Microsoft Teams (real-time push) |
| Meeting summaries | Microsoft Teams push + Outlook draft |

---

# 4. Category 2 — Data Management

User-maintained structured business databases. All data-management features share a common pattern: list view + search / filter / sort + inline editing + bulk operations + import / export.

| Feature | Data Type | Data Source | User Actions |
|---|---|---|---|
| **CRM** (Contacts) | Individuals (email, company, role, status, priority, relationship summary) | Auto-built from a 6-month email scan; supports manual entry, bulk import, and file upload (CSV, Excel, PDF, Word) | Edit any field, merge duplicates, archive, ignore, Excel export |
| **Projects** | Projects (status, momentum, participants, next step) | Inferred by the AI from email threads; supports manual entry and editing | Edit, merge, archive, Excel export |
| **Companies** | Organizations (identified by email domain) | Auto-derived from CRM + Projects; supports manual entry (e.g., target companies to monitor) | Edit name / aliases, toggle "Company Intelligence monitoring", delete (manual entries only), Excel export |
| **Cleanup** | AI cleanup suggestions across the three databases above | AI scans weekly, groups by confidence (high / medium / low), flags stale records | Approve or reject bulk actions |

### Shared Components

- **MergePicker** — search and merge duplicate records; fields are combined automatically.
- **BulkUploadModal** — drag-and-drop CSV / Excel / PDF / Word; the AI extracts records; the user previews and selects which records to import.

---

# 5. Category 3 — Workflow Tools

User-triggered AI tasks. The key distinction from Category 2 is that workflow tools are one-time tasks rather than ongoing data maintenance.

| Feature | Task | Trigger |
|---|---|---|
| **Outreach** | Batch-generate personalized outreach email drafts for a group of contacts | Two trigger paths: (1) a request in Teams (e.g., "draft outreach for contacts tagged Berlin Summit"); (2) an upload to a designated OneDrive folder (business-card photos, CSV, Excel, PDF). The AI extracts contacts and batch-drafts emails. All drafts are saved to Outlook Drafts for the user to review and send. |
| **Expenses** | Automatically convert receipts, invoices, and contracts into a reportable Excel ledger | Two paths: (1) **automatic** — email attachments or new OneDrive files are AI-recognized; vendor, amount, and date are extracted and written to `expenses_master.xlsx`; (2) **manual** — the user adds, edits, or deletes entries through the web UI, and exports to Excel. |
| **Draft Composer** | Single-email AI drafting with multi-turn refinement | Embedded in Reply Needed, Followup Needed, CRM, and other places. The user clicks "Draft reply"; the AI generates an initial draft; the user can iteratively refine it (e.g., "make it more formal", "add a thank-you line"); the final version is saved to Outlook Drafts. |

---

# 6. Supporting Infrastructure

The platform includes infrastructure that supports the three categories above. These are not standalone features, but they are part of the complete product experience:

| Module | Purpose |
|---|---|
| **Microsoft OAuth Login** | Users authenticate with their M365 account; all data access is via this OAuth token. |
| **Onboarding Wizard** (3 steps) | First-time setup: paste company website → confirm the AI-extracted company information → connect the Teams assistant bot. Background initialization (CRM, Projects, Companies, Profile drafting) runs automatically after completion. |
| **Profile & Context** | Three AI-context documents: Personal Profile (user identity), Business Profile (company positioning), Market Segments (markets of interest). All sections read these contexts at runtime. |
| **Activity Drawer** | Task-progress panel showing live execution logs for background tasks. |
| **In-app Chat** | Embedded chat with the AI assistant directly in the web app (an additional entry point beyond Teams). |
| **Settings Panel** | System configuration: `display_name`, `company_name`, bot connection management, Teams webhook URL, auto-cleanup preferences. |

---

# 7. Feature Index

| Question | Section |
|---|---|
| What does the platform proactively tell me each day? | §3 Category 1 (18 sections + delivery orchestration) |
| Can I manage my contact list and projects? | §4 Category 2 (CRM, Projects, Companies) |
| Can I send outreach emails in batch? | §5 Category 3 (Outreach) |
| How are expenses handled? | §5 Category 3 (Expenses) |
| How does the AI understand my business? | §6 Infrastructure (Profile & Context) |
| How does a new user get started? | §6 Infrastructure (Onboarding Wizard) |
| Where do I see the results? | §3.3 Output Channels |
