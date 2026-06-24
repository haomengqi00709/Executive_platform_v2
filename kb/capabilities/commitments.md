---
title: Commitments Tracking
describes_files:
  - src/sections/commitments_extract.py
  - src/sections/upcoming_commitments.py
  - src/sections/due_today.py
  - src/skills/commitments_extract/skill.md
  - src/skills/commitments_extract/validator.md
  - src/skills/due_today/skill.md
  - src/modules/commitments_store.py
  - src/modules/email_monitor.py
  - src/modules/screener.py
derived_from_commit: 617a540
last_synced: 2026-06-24
volatile_pointers:
  - src/skills/commitments_extract/skill.md
---

# Commitments Tracking

Turns email promises into a tracked to-do list.

## Storage (single source of truth)
Commitments live in the per-user SQLite store (`commitments_store.py`, one `store.db` per user) —
status (open/done/snoozed/dismissed) is inline on each row, so there is no snapshot-vs-state drift.
The legacy JSON files are kept only as synced read-only projections for older readers.

## Commitments Extract (`commitments_extract`)
Reads the **screened** inbox and extracts promises: who committed to what, by when. Each item is
tagged `my_commitment` vs `their_commitment`, with a description, `due_date` (+ confidence), priority,
and the source `email_id` / `conversation_id` (so the original email can be opened later).

- **AI:** extraction + validator. Excludes expense/calendar/automated tasks and "attend a meeting" items.
- **Incremental:** processed emails are cached in the store (`processed_emails`, ~30-day prune) so only
  new mail is analysed.
- **Real-time:** when the email monitor sees new mail it triggers an incremental extract, so the
  commitments DB reflects the inbox within ~1 minute (not only on a scheduled run).

## Upcoming Commitments (`upcoming_commitments`) / Due Today (`due_today`)
**Derived** views (no AI): commitments due in the next 7 days / due today, filtered live from the store.

## Lifecycle (done / asked / snoozed / auto-clear)
Each commitment's state is tracked inline. The bot can mark done / snooze / dismiss by the `#N` the
user saw. **A `their_commitment` auto-resolves when the counterparty replies in the same email thread**
(matched by `conversation_id`); if that reply itself contains a new promise, it is re-extracted.

## Common questions
- *"It computes 'due in 3 days' — is that AI?"* — No. Dates and day-counts are computed from data;
  the AI only judges *whether something is a real commitment* and extracts *what* was promised.
- *"If someone replies, does the 'waiting on them' item clear itself?"* — Yes, automatically.
