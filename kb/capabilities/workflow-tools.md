---
title: Workflow Tools (Outreach / Draft Composer)
describes_files:
  - src/modules/outreach.py
  - src/bot.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# Workflow Tools (Outreach / Draft Composer)

User-triggered, one-shot AI tasks (as opposed to standing data or scheduled
pushes).

## Outreach
Batch-generates personalized outreach email drafts for a group of contacts.
- **Triggers:** (1) ask the Teams bot (e.g. "draft outreach for contacts tagged
  Berlin Summit"); (2) drop a contact file (business-card photos / CSV / Excel /
  PDF) into a watched OneDrive folder → AI extracts contacts, then drafts.
- **Output:** all drafts saved to **Outlook Drafts** for the user to review and
  send. Endpoint `/api/outreach/run`; bot tool `run_outreach`. Implemented in
  `src/modules/outreach.py` (it is a tool, **not** a section).

## Draft Composer
Single-email AI drafting + multi-turn refine, embedded in Reply Needed, Followup
Needed, CRM, etc. The user clicks "Draft reply", the AI writes a draft, and the
user can iterate ("more formal", "add a thank-you") before saving.

## The hard rule
**Drafts are never auto-sent.** Everything the AI writes is saved to Outlook Drafts;
a human approves and sends. This is a platform-wide safety boundary.

## Common questions
- *"Did it email the client?"* — No. It only creates a draft; sending is always a
  manual human action.
