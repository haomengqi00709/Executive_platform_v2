---
title: Workflow Tools (Outreach / Draft Composer)
describes_files:
  - src/modules/outreach.py
  - src/bot.py
derived_from_commit: e7562a3
last_synced: 2026-06-19
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

## Conversational bot — list & pick, look before you ask
The Teams bot (`src/bot.py` `reply()`) shares one **[#N] convention** across every
list-returning tool: `_with_indices()` stamps each item with a 1-based `index`, the
bot displays items as `[#1] … [#2] …`, and a later "do #2" is resolved back to the
item's canonical id (email_id / event_id / draft_id / contact email). Contacts
(`find_contacts_by_name`) and groups (`list_my_groups`) are part of this too.

**Disambiguation rule:** when the user names a person/target for an action
("schedule a meeting with Daniel"), the bot must **look first** —
`find_contacts_by_name` — before asking anything. One match → proceed; several →
present them as a `[#N]` list and ask which; none → ask for the email. It never
replies a vague "I found a few, please specify" without first looking them up and
listing them.

**Completion gate:** every turn is verified against ground-truth (which action
tools actually succeeded), not the draft reply's own claims. A blind "please
specify" with no lookup is treated as *actionable* and re-driven to look + list;
the bot only stops to ask the user when info is genuinely user-only (a time, a
confirmation) or several candidates genuinely match after a lookup.

## The hard rule
**Drafts are never auto-sent.** Everything the AI writes is saved to Outlook Drafts;
a human approves and sends. This is a platform-wide safety boundary.

## Common questions
- *"Did it email the client?"* — No. It only creates a draft; sending is always a
  manual human action.
