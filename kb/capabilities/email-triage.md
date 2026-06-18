---
title: Email Triage
describes_files:
  - src/sections/reply_needed.py
  - src/sections/followup_needed.py
  - src/skills/reply_needed/skill.md
  - src/skills/reply_needed/validator.md
  - src/skills/followup_needed/skill.md
  - src/skills/followup_needed/validator.md
  - src/modules/screener.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/reply_needed/skill.md
  - src/skills/followup_needed/skill.md
---

# Email Triage

Two complementary views over the executive's mail: what *they* owe a reply to, and
what *others* owe them.

## Emails Awaiting Reply (`reply_needed`)
Inbound emails that genuinely need the executive's reply, sorted by priority, each
with a short reason and a suggested opening line.

- **Data source:** the **screened** inbox + sent folder + CRM + projects.
- **AI:** classification + a second-pass validator.

## Sent — No Response (`followup_needed`)
Emails the executive sent that haven't gotten a reply, with how long they've been
waiting and a suggested follow-up tone.

- **Data source:** sent folder + inbox conversation-latest + CRM/projects.
- **Note:** `days_waiting` is **computed from `sentDateTime`**, never guessed by
  the AI (a past bug where the model invented wait times is why this is a hard rule).

## The screener (always first)
Before any inbound email is shown to the user, it passes through
`src/modules/screener.py` — a two-stage filter (CRM ignore-list, then an AI batch
judging "does the CEO need to personally handle this?"). Only `screened_out=False`
emails surface. This is a platform-wide invariant for any feature that *presents*
inbound mail.

## Draft Composer (embedded here)
From either view the user can click "Draft reply" → the AI writes a draft and can
refine it over multiple turns ("more formal", "add thanks"). Drafts are saved to
**Outlook Drafts only — never auto-sent.** See [workflow-tools](workflow-tools.md).

## Common questions
- *"Why isn't email X showing up?"* — It was likely screened out (marketing/FYI/
  receipt) or the sender is on the CRM ignore list.
- *"Can I tell it to ignore a category?"* — Yes, via the per-section instruction.
