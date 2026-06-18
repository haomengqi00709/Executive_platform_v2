---
title: Daily Briefing & Recap
describes_files:
  - src/sections/ai_summary.py
  - src/sections/yesterday_recap.py
  - src/skills/ai_summary/skill.md
  - src/skills/yesterday_recap/skill.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/ai_summary/skill.md
  - src/skills/yesterday_recap/skill.md
---

# Daily Briefing & Recap

The platform's two daily digest capabilities — one forward-looking, one backward.

## AI Morning Summary (`ai_summary`)
A short (≈200–300 word) AI-written briefing the executive reads first thing.
It synthesizes, into one narrative: today's agenda, which emails are priorities,
key relationships worth attention, overdue commitments, what's coming up, slipping
relationships, and relevant industry news.

- **Data source:** today's calendar + the screened inbox + market/industry news.
- **Trigger:** Scheduled (pushed as a morning brief; see [delivery](delivery.md)).
- **AI:** Gemini text generation. The exact wording rules live in
  `src/skills/ai_summary/skill.md` (surfaced live — ask the chat for it).
- **Boundary:** the AI writes prose and judgments; it does **not** invent counts,
  names, or dates — those come from the underlying data, not the model.

## Yesterday's Recap (`yesterday_recap`)
A backward-looking summary of the previous day: emails sent/received that mattered,
meetings that happened, and commitments that were newly created.

- **Data source:** Graph inbox/sent/calendar for the prior day + commitments.
- **Trigger:** Scheduled.

## Common questions
- *"Can I change what the morning summary includes / its tone?"* — Yes, per user,
  via the section instruction (`.data/{uid}/instructions/ai_summary.md`), editable
  from the frontend Settings page or the Teams bot.
- *"Where does it get delivered?"* — Web Dashboard always; Teams if included in a
  scheduled briefing. See [delivery](delivery.md).
