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
  - src/modules/email_store.py
derived_from_commit: 617a540
last_synced: 2026-06-24
volatile_pointers:
  - src/skills/reply_needed/skill.md
  - src/skills/followup_needed/skill.md
---

# Email Triage

Two complementary views over the executive's mail: what *they* owe a reply to, and what *others* owe them.

## Emails Awaiting Reply (`reply_needed`)
Inbound emails that genuinely need the executive's reply, sorted by priority, each with a short reason
and a suggested opening line.

- **Data source:** the **screened** inbox + sent folder + CRM + projects.
- **AI:** classification + a second-pass validator.
- **Handled state is live:** once the user drafts/sends a reply, that email drops off the list
  immediately — a durable "handled" annotation in the store (`email_store.py`) is overlaid at read
  time, so it disappears without re-running the costly section ("drafted but still shows" is fixed).

## Sent — No Response (`followup_needed`)
Emails the executive sent that haven't gotten a reply, with how long they've been waiting and a
suggested follow-up tone.

- **Data source:** sent folder + inbox conversation-latest + CRM/projects.
- **`days_waiting` is computed from `sentDateTime`**, never guessed by the AI (a past hallucinated-
  wait-time bug is why this is a hard rule).
- **Dismissable:** "skip the follow up to Daniel" removes that follow-up (records a durable
  `followup_dismissed` annotation, kept separate from reply state) and it stays gone.

## The screener (always first)
Before any inbound email is shown, it passes through `src/modules/screener.py` — a two-stage filter
(CRM ignore-list, then an AI batch judging "does the CEO need to personally handle this?"). Only
`screened_out=False` emails surface. Platform-wide invariant for any feature that *presents* inbound mail.

## Draft Composer (embedded here)
From either view the user can "Draft reply" → the AI writes a draft and refines it over turns. Drafts
are saved to **Outlook Drafts only — never auto-sent.** See [workflow-tools](workflow-tools.md). To
read the full original of an email behind a list item, the bot has `open_email`.

## Common questions
- *"Why isn't email X showing up?"* — It was likely screened out (marketing/FYI/receipt), the sender
  is on the CRM ignore list, or you already drafted/replied (handled → overlaid out).
- *"Can I tell it to ignore a category?"* — Yes, via the per-section instruction.
