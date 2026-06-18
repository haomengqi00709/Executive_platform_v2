---
title: Data Layout & Auth
describes_files:
  - src/auth.py
  - src/graph.py
  - CLAUDE.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# Data Layout & Auth

## Auth (`src/auth.py`)
- Microsoft MSAL OAuth — web authorization-code flow + device-code flow (local dev
  and the bot account). Authority is `/common` (multi-tenant).
- JWT session cookies (httponly, 7-day).
- Per-user token cache at `.data/_sessions/{user_id}.json`;
  `get_valid_access_token(uid)` auto-refreshes (5-min buffer).
- First login triggers an init scan (CRM + projects + profile draft).

## Microsoft Graph (`src/graph.py`)
`GraphClient(token)` wraps Graph for mail, calendar, OneDrive, mail-send, Teams
chat, To-Do, and online meetings. **Calendar must use `get_calendar_view()`**
(calendarView endpoint), never `get_events(filter=...)`.

## Per-user data (hard isolation invariant)
Everything lives under `.data/{user_id}/`:
```
settings.json · crm.json · projects.json
profile/ (business_profile.md, market_segments.md, init_status.json)
instructions/{section_id}.md      ← per-user prompt overrides
results/{section_id}.json         ← latest section output
wiki/                             ← Meeting DB (legacy folder name; NOT a wiki)
expenses/ (expenses_master.xlsx, dedup files)
commitments_cache.json · commitments_state.json
…seen/state files per intel section, email_monitor.json, teams_bot.json, bot.sqlite
```
Sessions are separate: `.data/_sessions/{user_id}.json`.

> **The KB you're reading is NOT under `.data/`** — it's repo-wide, in git. Do not
> confuse `wiki/` (per-user meeting DB) with `kb/` (this knowledge base).

## Bot architecture
Two-account model: the assistant bot (Audrey) account polls the owner's 1:1 Teams
chat on their behalf. Bot auth matches identities by **email, not uid**; the bot
token cache is per-bot and never falls back to a shared pile.
