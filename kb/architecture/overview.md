---
title: System Overview
describes_files:
  - CLAUDE.md
  - src/server.py
  - src/ai.py
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# System Overview

A multi-tenant Executive AI Platform. It connects to a user's Microsoft 365
(Outlook, Calendar, OneDrive, Teams) via OAuth, runs intelligence sections, and
delivers output to a Web Dashboard and Teams (via a bot account).

## Shape
```
Microsoft Graph ─┐
Gemini API ──────┼─▶ src/sections/*.run() ─▶ .data/{uid}/results/{sid}.json ─▶ FastAPI ─▶ Frontend / Teams
OneDrive / mail ─┘
```
- **Backend:** FastAPI (`src/server.py`) — routes, the section registry
  (`_SECTION_RUNNERS`), Teams formatters, and the background scheduler.
- **AI:** Google Gemini via `src/ai.py` (`generate`, `generate_with_search`,
  `transcribe_*`, `extract_json`). The model is set in one place (a default +
  `GEMINI_MODEL` env override) — ask the chat / read `src/ai.py` for the current
  value rather than trusting any doc, since it changes.
- **Auth:** MSAL OAuth + JWT session cookies (`src/auth.py`).

## Core design principles (from CLAUDE.md)
1. **One section → one data source → one result file.** No fallback paths. Missing
   data ⇒ `status: "not_run"`, not "read from somewhere else".
2. **Multi-user isolation from line 1.** Every function takes `data_dir: Path`;
   all per-user state lives under `.data/{user_id}/`. No global paths.
3. **Screener before email AI.** Any feature presenting inbound mail filters through
   the screener first (except expenses).
4. **AI judges, code computes.** The AI makes judgments and writes prose; it never
   computes facts (counts, dates, "days waiting") that can be derived from data.
5. **Standard result shape:** `{id, status, last_run, items, count, empty}`.

## The two frontends
- `frontend/` — React + TypeScript + Vite (the primary client-facing UI).
- (`Frontend_1/` is an older polished mock UI.)
