---
title: Relationship Health
describes_files:
  - src/sections/relationship_health.py
  - src/modules/crm.py
  - src/modules/crm_store.py
  - src/skills/relationship_health/skill.md
derived_from_commit: 617a540
last_synced: 2026-06-24
volatile_pointers:
  - src/skills/relationship_health/skill.md
---

# Relationship Health

Tracks how warm or cold the executive's key relationships are.

## Relationship Health (`relationship_health`)
For key contacts: contact frequency, "cooling" signals (a relationship going quiet), and a suggested
action, plus an AI-written reminder.

- **Data source:** CRM + projects + Graph email metadata over ~90 days. The CRM itself is stored in
  the per-user `store.db` (`crm_store.py`); `crm.json` is a synced read-only projection.
- **AI boundary:** the health status and the metrics (emails in last 30 days, trend, days since last
  inbound) are **computed from email metadata** — the AI only writes the reminder/suggested-action
  prose, never the numbers.
- **Reference implementation:** `src/sections/relationship_health.py` is the cleanest example of the
  section + validator pattern in the codebase.

> Querying the CRM (list contacts by status/priority/tag, look a contact up, edit a contact) is a
> separate cluster — see [data-management](data-management.md).

## Common questions
- *"How does it decide a relationship is cooling?"* — From measured contact frequency (counts and
  recency), not the model's opinion.
