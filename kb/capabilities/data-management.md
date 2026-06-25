---
title: Data Management (CRM / Projects / Companies)
describes_files:
  - src/modules/crm.py
  - src/modules/crm_store.py
  - src/modules/projects.py
  - src/modules/projects_store.py
  - src/modules/companies.py
  - src/modules/companies_store.py
  - src/modules/db_cleaner.py
  - src/modules/profile_init.py
  - src/bot_tools/contacts/list_crm_contacts/tool.py
  - src/bot_tools/contacts/get_contact_history/tool.py
  - src/bot_tools/contacts/update_crm_contact/tool.py
  - src/bot_tools/contacts/tag_contact/tool.py
  - src/bot_tools/companies/list_companies/tool.py
derived_from_commit: 97215fd
last_synced: 2026-06-25
---

# Data Management (CRM / Projects / Companies)

The structured business records the user maintains inside the platform. List view + search/filter/sort
+ inline edit + bulk ops + import/export.

## Storage (single source of truth)
CRM, Projects, AND Companies all live in the per-user SQLite `store.db` (`crm_store.py` /
`projects_store.py` / `companies_store.py`); the old `crm.json` / `projects.json` / `companies.json`
are kept as synced read-only projections so existing readers are unchanged. Writes are
**edit-preserving**: an AI rebuild only overwrites AI-derived fields and never the user's columns
(notes, tags, priority, ignore, status edits). Migration from the legacy JSON is lossless and
reversible. Every frontend data operation on a mutable business domain now lands in the store.

## CRM (contacts)
People — email, company, role, status, priority, relationship summary, notes, tags.
- **Source:** auto-built from ~6 months of email history (`crm.py`); AI enriches company/role/status/
  summary. Also manual add, bulk import, or file upload (CSV/Excel/PDF/Word).
- **Edit:** any field, merge duplicates, archive, **ignore** (ignored contacts feed the email
  screener's ignore-list), Excel export.
- **Ask the bot:** "who are my high-priority contacts / clients / internal contacts / everyone tagged X"
  → `list_crm_contacts` (filters the curated CRM by status/priority/tag — NOT inbox volume); "who is X /
  what's my history with X" → `get_contact_history` (full CRM profile + writing style + meetings);
  "mark X high priority / add a note" → `update_crm_contact`; "tag X as Y / add X to the Y group" →
  `tag_contact` (one named contact).

## Projects
See [projects](projects.md) — same store powers the data view, the project sections, and the bot's
`modify_project`.

## Companies
Organizations, **identified by email domain** (not by name). A DERIVED view — identity/contacts/
projects/status recomputed from CRM + Projects — plus a user-state layer (monitor toggle, ignore,
notes, priority, name, manual adds) that persists across rebuilds. That user state lives in the store
(`companies_store.py`); `companies.json` is a synced projection. The `monitor_intelligence` / `ignore`
/ `priority` edits directly drive which companies **Company Intelligence** actually runs on.
- **Ask the bot:** "what companies am I tracking / monitoring for intelligence", "list my companies"
  → `list_companies` (default shows only the companies intelligence runs on; filterable by status/priority).

## Cleanup
A weekly AI scan proposes tidy-ups across CRM/Projects (dedup, stale flags), grouped by confidence;
the user approves/rejects in bulk. **Merges and archives now persist through the store** — so a
merged-away duplicate or an archive is durable and won't be resurrected by the next refresh.

## Shared components
- **MergePicker** — find a duplicate by search and merge, auto-combining fields.
- **BulkUploadModal** — drag in CSV/Excel/PDF/Word; AI extracts records; user previews and imports.

## Common questions
- *"Where did all these contacts come from?"* — An initial scan of your sent/received mail at first login.
- *"If I edit a contact, will the daily rebuild overwrite it?"* — No; user fields are preserved.
