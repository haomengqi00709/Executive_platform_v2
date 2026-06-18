---
title: Project Tracking
describes_files:
  - src/sections/project_status.py
  - src/sections/projects_needing_attention.py
  - src/modules/projects.py
  - src/skills/project_status/skill.md
  - src/skills/projects_needing_attention/skill.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/project_status/skill.md
  - src/skills/projects_needing_attention/skill.md
---

# Project Tracking

A portfolio view of the executive's active projects, inferred from email threads.

## Project Status (`project_status`)
The full portfolio: every project with its status, momentum, last activity, and
suggested next step.

## Projects Needing Attention (`projects_needing_attention`)
A filtered, actionable subset: projects that are stalled, flagged as needing
attention, or newly forming.

- **Data source (both):** `projects.json`, built/refreshed by
  `src/modules/projects.py`, which clusters email conversations and asks the AI for
  each cluster's status / momentum / next_action.
- **Refresh:** a scheduled daily projects refresh (06:30 UTC) keeps `projects.json`
  current; users can also add/edit/merge projects manually (see
  [data-management](data-management.md)).
- **AI:** validator-only at the section layer (the heavy inference happens in
  `projects.py`).

## Common questions
- *"Where do projects come from?"* — The AI infers them from email conversations;
  they aren't entered by hand (though you can add/edit them).
