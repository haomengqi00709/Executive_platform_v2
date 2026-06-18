---
title: How a Section Works
describes_files:
  - src/server.py
  - src/modules/validator.py
  - src/modules/screener.py
  - src/sections/relationship_health.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# How a Section Works

A "section" is one unit of intelligence (e.g. `reply_needed`). Each is a file in
`src/sections/{id}.py` exposing `run(graph, ai, data_dir, settings, progress)` and
returning the standard result shape `{id, status, last_run, items, count, empty}`.

## The three prompt layers (per section)
```
src/skills/{id}/skill.md      ← system-level: what the section is, default rules
src/skills/{id}/validator.md  ← (optional) extra second-pass validator rules
.data/{uid}/instructions/{id}.md ← per-user free-text override (highest priority)
```
At runtime an AI-shaped section calls `validate_output(...)` (`validator.py`), which
loads all three plus the items list, and the AI returns keep/drop/priority decisions
per item. If the validator errors, it returns the original items (fail-safe).

> **Prompt questions are answered LIVE.** "What's the current prompt for X?" is
> answered by serving `src/skills/{X}/skill.md` verbatim, not by this KB — prompts
> change too often to freeze. Only 14 of the ~19 sections have a `skill.md`; the
> rest are derived/read-only and have no prompt.

## The screener
`src/modules/screener.py` is a required pre-filter for any feature that *presents*
inbound mail: a CRM ignore-list stage, then an AI batch judging "must the CEO
personally handle this?". Only `screened_out=False` items surface.

## Adding/changing a section
- New section ⇒ 5 files: `src/sections/{id}.py`, `src/skills/{id}/skill.md`, register
  in `src/server.py` (`_SECTION_RUNNERS` + Teams formatter), `src/bot.py`
  (`SECTION_IDS`), `src/modules/validator.py` (`_SECTION_TITLES` + formatter).
- Change behavior system-wide ⇒ edit `src/skills/{id}/skill.md`.
- Change behavior for one user ⇒ `.data/{uid}/instructions/{id}.md`.

**Reference implementation:** `src/sections/relationship_health.py` (cleanest).
