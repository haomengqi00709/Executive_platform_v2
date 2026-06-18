---
title: Commitments Tracking
describes_files:
  - src/sections/commitments_extract.py
  - src/sections/upcoming_commitments.py
  - src/sections/due_today.py
  - src/skills/commitments_extract/skill.md
  - src/skills/commitments_extract/validator.md
  - src/skills/due_today/skill.md
  - src/modules/commitments_cache.py
  - src/modules/commitments_state.py
  - src/modules/screener.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/commitments_extract/skill.md
---

# Commitments Tracking

Turns email promises into a tracked to-do list.

## Commitments Extract (`commitments_extract`)
Reads the **screened** inbox and extracts promises: who committed to what, by when.
Each item is tagged `my_commitment` vs `their_commitment`, with a description,
`due_date` (+ confidence), and priority.

- **AI:** extraction + validator. Excludes expense/calendar/automated tasks and
  "attend a meeting" items.
- **Performance:** incremental — per-email results are cached
  (`commitments_cache.py`, ~30-day prune) so re-runs only process new mail.

## Upcoming Commitments (`upcoming_commitments`)
A **derived** view (no AI, no cache file): commitments due in the next 7 days,
filtered live from `commitments_extract`'s result. Past-due "attend a meeting"
items are dropped.

## Due Today (`due_today`)
A **derived** view: commitments/to-dos due today.

## Lifecycle (done / asked / snoozed)
`commitments_state.py` tracks each commitment's state. `mark_done_by_email_id()`
can auto-resolve a `their_commitment` when the other party replies (wired as email
monitoring integrates).

## Common questions
- *"It computes 'due in 3 days' — is that AI?"* — No. Dates and day-counts are
  computed from data; the AI only judges *whether something is a real commitment*
  and extracts *what* was promised.
