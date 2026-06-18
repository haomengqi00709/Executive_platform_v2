---
title: Data Management (CRM / Projects / Companies)
describes_files:
  - src/modules/crm.py
  - src/modules/projects.py
  - src/modules/profile_init.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# Data Management (CRM / Projects / Companies)

The structured business records the user maintains inside the platform. All share a
pattern: list view + search/filter/sort + inline edit + bulk ops + import/export.

## CRM (contacts)
People — email, company, role, status, priority, relationship summary.
- **Source:** auto-built by scanning ~6 months of email history (`crm.py`), AI
  enriches each contact (company/role/status/summary). Also manual add, bulk
  import, or file upload (CSV/Excel/PDF/Word).
- **Actions:** edit any field, merge duplicates, archive, **ignore** (ignored
  contacts feed the email screener's ignore-list), Excel export.

## Projects
See [projects](projects.md) — the same `projects.json` powers both the Projects
data view and the project sections.

## Companies
Organizations, **identified by email domain** (not by name). Auto-derived from CRM +
Projects; users can manually add a company to watch and toggle "Company Intelligence
monitoring".

## Cleanup
A weekly AI scan proposes tidy-ups across CRM/Projects/Companies (dedup, stale
flags), grouped by confidence (high/medium/low); the user approves or rejects in
bulk.

## Shared components
- **MergePicker** — find a duplicate by search and merge, auto-combining fields.
- **BulkUploadModal** — drag in CSV/Excel/PDF/Word; AI extracts records; user
  previews and picks which to import.

## Common questions
- *"Where did all these contacts come from?"* — An initial scan of your sent/received
  mail (`profile_init.py` + `crm.py`) at first login.
