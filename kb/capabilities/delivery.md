---
title: Delivery & Push Orchestration
describes_files:
  - src/modules/email_monitor.py
  - src/modules/teams_bot.py
  - src/server.py
derived_from_commit: 617a540
last_synced: 2026-06-24
---

# Delivery & Push Orchestration

How section output reaches the user, and how proactive pushes are configured.

## Output channels
- **Web Dashboard** — all sections, with full lists and inline actions.
- **Microsoft Teams** — pushed via the dedicated assistant bot (Audrey) for
  scheduled briefings, real-time email alerts, and meeting summaries.
- **Outlook Drafts** — generated email drafts (replies, follow-ups, outreach).

## Push mechanisms
- **Scheduled Briefings** — the user configures a cron time, a set of sections, and
  a channel (e.g. "weekdays 7am → AI Summary + Due Today + Meetings Today"). Each
  user can have several independent briefings. *(Per-user schedule config is on the
  roadmap; today the scheduler runs fixed jobs.)*
- **Email Monitor** (`email_monitor.py`) — polls the inbox (~1 min); a new email is
  triaged and pushed to Teams immediately or batched into a digest. It also updates
  the store in real time: **extracts any new commitments** and **auto-clears a
  `their_commitment` when the counterparty replies** in-thread. Configurable
  working-hours window and digest interval.
- **Meeting Autoresponder** — a new OneDrive recording auto-triggers the meeting
  summary → Teams push → Outlook follow-up draft. See [meetings](meetings.md).
- **Per-section Instructions** — every section accepts a free-text user instruction
  that steers its AI behavior.

## Background scheduler (`src/server.py` startup)
Fixed jobs today: Teams bot poll (10s), email monitor poll (1m), expense scan (1m),
meeting-prep (5m), meeting-recording scan (20m), CRM refresh (06:00 UTC), projects
refresh (06:30 UTC), companies refresh (06:45 UTC), DB cleanup (weekly Mon 07:00 UTC).

## Teams Adaptive Card rules (hard-won)
Never use `{"type":"Separator"}` as an element (Teams silently drops the whole
card) — use `"separator": true` on the next element. `Action.ToggleVisibility` is
unsupported via Teams webhooks.

## Common questions
- *"Can I get the morning brief at a custom time?"* — Per-user scheduling is planned;
  current pushes run on fixed schedules.
