---
title: Relationship Health
describes_files:
  - src/sections/relationship_health.py
  - src/modules/crm.py
  - src/skills/relationship_health/skill.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/relationship_health/skill.md
---

# Relationship Health

Tracks how warm or cold the executive's key relationships are.

## Relationship Health (`relationship_health`)
For key contacts: contact frequency, "cooling" signals (a relationship going
quiet), and a suggested action, plus an AI-written reminder.

- **Data source:** CRM + projects + Graph email metadata over ~90 days.
- **AI boundary:** the health status and the metrics (e.g. emails in last 30 days,
  trend, days since last inbound) are **computed from email metadata** — the AI
  only writes the reminder/suggested-action prose, never the numbers.
- **Reference implementation:** `src/sections/relationship_health.py` is the
  cleanest example of the section + validator pattern in the codebase.

## Common questions
- *"How does it decide a relationship is cooling?"* — From measured contact
  frequency (counts and recency), not the model's opinion.
