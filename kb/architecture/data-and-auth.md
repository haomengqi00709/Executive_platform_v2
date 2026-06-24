---
title: Data Layout & Auth
describes_files:
  - src/auth.py
  - src/graph.py
  - src/modules/db_helpers.py
  - CLAUDE.md
derived_from_commit: 617a540
last_synced: 2026-06-24
---

# Data Layout & Auth

## Auth (`src/auth.py`)
- Microsoft MSAL OAuth — web authorization-code flow + device-code flow (local dev and the bot
  account). Authority is `/common` (multi-tenant).
- JWT session cookies (httponly, 7-day).
- Per-user token cache at `.data/_sessions/{user_id}.json`; `get_valid_access_token(uid)` auto-refreshes
  (5-min buffer).
- First login triggers an init scan (CRM + projects + profile draft).

## Microsoft Graph (`src/graph.py`)
`GraphClient(token)` wraps Graph for mail, calendar, OneDrive, mail-send, Teams chat, To-Do, and online
meetings. **Calendar must use `get_calendar_view()`** (calendarView endpoint), never `get_events(filter=...)`.

## Per-user SQLite store — the single source of truth
Each user has one **`.data/{user_id}/store.db`** (SQLite, opened via `db_helpers.open_sqlite` =
WAL + busy_timeout, SMB-safe). It holds all the **mutable** per-user state — commitments, email
poller/handled annotations, CRM contacts, projects — each domain in its own tables. Status/edits are
inline on the rows, so there is no snapshot-vs-live drift. Migration from the legacy JSON is **lazy,
lossless, and reversible** (a durable verdict is written to a meta table and surfaced by
`GET /api/admin/migration-status`).

The legacy JSON files still exist but are **synced read-only projections** of the store (regenerated on
every write), so older readers and the dashboard keep working unchanged. External raw data (email
bodies, calendar, recordings) is **never mirrored** into the store — only pointers (email_id /
conversation_id / meeting_id) + derived fields are kept; the original is fetched live via the pointer.

## Per-user data (hard isolation invariant)
Everything lives under `.data/{user_id}/`:
```
store.db                          ← SOURCE OF TRUTH (commitments / email / CRM / projects)
settings.json
crm.json · projects.json          ← synced projections of store.db
profile/ (business_profile.md, market_segments.md, personal_profile.md, init_status.json)
instructions/{section_id}.md      ← per-user prompt overrides
results/{section_id}.json         ← latest section output (rendered snapshots)
wiki/                             ← Meeting DB (legacy folder name; NOT a wiki)
expenses/ (expenses_master.xlsx)  ← separate Excel ledger (not in the store, by design)
…legacy commitments_*.json / email_monitor.json kept as projections; teams_bot.json; bot.sqlite
```
Sessions are separate: `.data/_sessions/{user_id}.json`.

> **The KB you're reading is NOT under `.data/`** — it's repo-wide, in git. Do not confuse `wiki/`
> (per-user meeting DB) with `kb/` (this knowledge base).

## Bot architecture
Two-account model: the assistant bot (Audrey) account polls the owner's 1:1 Teams chat on their
behalf. Bot auth matches identities by **email, not uid**; the bot token cache is per-bot and never
falls back to a shared pile.
