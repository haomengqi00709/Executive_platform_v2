# CEO Platform v2 — Codebase Map

A complete navigation map of the v2 backend + frontend.
17 sections · 12 modules · ~14,000 lines of Python · React frontend.

Last updated: 2026-05-23

---

## 1. Project Tree

```
CEO_platform_v2/
├── CLAUDE.md                  ← v2 architecture principles + product positioning
├── API_DATA_REFERENCE.md      ← Graph API field reference (what each endpoint returns)
├── AUTH_GUIDE.md              ← Auth + Graph foundation notes
├── Dockerfile                 ← Container build (Railway deploy)
├── Procfile                   ← Process entrypoint for Railway
├── requirements.txt           ← Python deps
├── src/                       ← Backend (FastAPI + Gemini + Graph)
│   ├── server.py              ← FastAPI app: routes, scheduler, section registry, Teams formatters
│   ├── bot.py                 ← Teams bot agent (Gemini function-calling + tool definitions)
│   ├── ai.py                  ← Gemini client wrapper (generate / generate_with_search / transcribe)
│   ├── auth.py                ← MSAL OAuth (web flow + device code) + JWT session cookies
│   ├── graph.py               ← Microsoft Graph API HTTP client (~30 methods)
│   ├── slash.py               ← Slash-command handler (/help, /context, /settings)
│   ├── tools.py               ← Atomic tools for older bot loops (graph queries, frequency reports)
│   ├── sections/              ← 17 section implementations
│   ├── skills/                ← Section-level skill.md + validator.md
│   └── modules/               ← 12 shared modules (CRM, projects, screener, validator, …)
├── frontend/                  ← React + TypeScript + Vite + Tailwind 4
│   ├── package.json
│   ├── index.html
│   └── src/
│       ├── App.tsx            ← Single-file app (~1950 lines, all pages)
│       ├── main.tsx
│       └── index.css
├── test_*.py                  ← Top-level integration tests
└── test_scripts/              ← Ad-hoc test scripts (e.g. test_ai_summary.py)
```

---

## 2. Data Flow

```
External sources                             User-facing channels
─────────────────                            ──────────────────────
Microsoft Graph    ─┐                ┌──── Teams chat (Audrey bot)
  (mail / calendar /│                │
   OneDrive / Teams)│                │       ▲
                    ▼                │       │  push (section result formatted as Markdown)
              ┌──────────┐           │       │
Gemini API ──▶│ src/sections/ ──▶ .data/{uid}/results/{sid}.json ──▶ _send_to_bot()
  (LLM + grounded   │ run()    │     │       │
   search +         └──────────┘     │       │ poll user reply
   document AI)     reads:           │       │
                      ─ Graph live   │       ▼
                      ─ crm.json     │
                      ─ projects.json│   FastAPI routes
                      ─ instructions │   ──────────────
                      ─ skill.md     ├── /api/sections/{id}           — GET cached result
                      ─ validator.md ├── /api/sections/{id}/run       — POST trigger
                                     ├── /api/sections/{id}/instructions
                                     ├── /api/crm/, /api/projects/, /api/profile/
                                     │
                                     └── Frontend (React SPA on :3000)
                                          calls these endpoints
```

**Key principle (CLAUDE.md):** one section → one data source → one result file.
No fallback to another data source. If data is missing, return `status: "not_run"`.

---

## 3. Section Catalog (17 sections)

Sections fall into **two categories**:
- **Scheduled** — runs on schedule, pushed to user as morning brief cards
- **Triggered** — runs on event (new email, new meeting, new receipt)

| Section ID | Display Name | Category | Data Source | AI Used | User-customizable via `instruction.md` |
|------------|--------------|----------|-------------|---------|-----------------------------------------|
| `ai_summary` | AI Morning Briefing | Scheduled | calendar + screened inbox + news | ✅ Gemini text gen | ✅ |
| `reply_needed` | Emails Awaiting Reply | Scheduled | screened inbox + sent folder + CRM + projects | ✅ extract + validator | ✅ |
| `followup_needed` | Sent — No Response | Scheduled | sent folder + inbox conv_latest + CRM/projects | ✅ extract + validator | ✅ |
| `commitments_extract` | Commitments | Scheduled | screened inbox (incremental cache) | ✅ extract + validator | ✅ |
| `upcoming_commitments` | Upcoming Commitments | Derived | `commitments_extract.json` | ❌ pure filter | ❌ (Teams suppressed; frontend uses) |
| `due_today` | Due Today | Derived | `commitments_extract.json` | ✅ validator only | ✅ |
| `yesterday_recap` | Yesterday's Recap | Scheduled | Graph inbox/sent/calendar (1 day) + commitments | ✅ validator only | ✅ |
| `recent_meetings` | Recent Meetings | Triggered | `data_dir/wiki/_index.json` | ❌ read-only | ❌ (display only) |
| `meeting_action_items` | Meeting Action Items | Triggered | `data_dir/wiki/{meeting_id}.json` | ❌ read-only | ❌ (display only) |
| `meetings_today` | Today's Meetings | Live | Graph `calendarView` (today) | ✅ validator only | ✅ |
| `expenses` | Document Capture | Triggered | inbox attachments + OneDrive (Teams images) | ✅ Gemini vision | ❌ (deterministic extraction) |
| `market_intelligence` | Market Intelligence | Scheduled | Gemini Google Search grounding | ✅ search + extract + validator | ✅ |
| `company_intelligence` | Company Intelligence | Scheduled | CRM + projects + Gemini Search | ✅ search + extract + validator | ✅ |
| `relationship_health` | Relationship Health | Scheduled | CRM + projects + Graph metadata (90d) | ✅ writes reminders | ✅ |
| `business_insights` | Weekly Brief | Scheduled (weekly) | aggregates other section results | ✅ writes narrative | ✅ |
| `projects_needing_attention` | Projects Needing Attention | Scheduled | `projects.json` | ✅ validator only | ✅ |
| `project_status` | Project Status | Scheduled | `projects.json` | ✅ validator only | ✅ |

**Standard result shape** (every section produces this):
```json
{
  "id": "<section_id>",
  "status": "fresh | stale | not_run | running | error",
  "last_run": "<ISO timestamp>",
  "items": [ ... ],
  "count": N,
  "empty": false
}
```

**Registered in:** `src/server.py::_SECTION_RUNNERS` dict + `src/bot.py::SECTION_IDS` dict.

---

## 4. Module Catalog (`src/modules/`)

| File | Purpose | Used By |
|------|---------|---------|
| `crm.py` | Build/refresh contact DB from email history. AI per contact: company/role/status/summary. | `relationship_health`, `company_intelligence`, `reply_needed`, `followup_needed`, server scheduler |
| `projects.py` | Build/refresh project DB from email conversations. AI per cluster: status/momentum/next_action. | `project_status`, `projects_needing_attention`, `relationship_health`, `company_intelligence`, server |
| `screener.py` | Two-stage filter (CRM ignore list → AI batch). Adds `screened_out` flag. **Required before any email-content AI.** | `reply_needed`, `followup_needed`, `commitments_extract`, `ai_summary`, `projects.py` |
| `validator.py` | Generic second-pass review of section items. Reads `skills/{sid}/skill.md` + `instructions/{sid}.md`. **All AI-shaped sections use this.** | Every AI-using section |
| `profile.py` | User's business profile + market segments docs (`profile/business_profile.md`, `profile/market_segments.md`). Combined text injected into prompts. | `ai_summary`, `market_intelligence`, `company_intelligence`, `business_insights` |
| `profile_init.py` | AI-generated first-time profile drafts (from user's sent emails, CRM, projects). | server's first-login init |
| `commitments_cache.py` | Incremental cache for `commitments_extract` (per-email AI results, 30-day prune). | `commitments_extract` |
| `commitments_state.py` | Lifecycle tracking: done/asked/snoozed. `mark_done_by_email_id()` auto-resolves when other party replies. | bot, `commitments_extract`, `due_today`, `upcoming_commitments` |
| `wiki.py` | Meeting DB. Stores transcripts, summaries, action items per meeting (`wiki/_index.json` + `{meeting_id}.json`). | `recent_meetings`, `meeting_action_items`, `m03_meeting.py` |
| `m03_meeting.py` | Meeting intelligence: OneDrive .mp4 → VTT/audio/video transcription chain → AI summary + actions. | server's `/api/m03/scan` route + scheduler |
| `m05_expense.py` | **Compatibility bridge** — re-exports symbols from `src/sections/expenses.py` so old imports still work. Don't add new logic here. | `teams_bot.py` (legacy import) |
| `email_monitor.py` | Real-time inbox polling, triage, immediate-push or digest queue routing. | server scheduler (`_poll_email_monitor_all_users`) |
| `teams_bot.py` | Polling loop for Teams 1:1 chat. Detects new messages + receipt attachments. Calls `bot.py` for text replies. | server scheduler (`_poll_teams_bot_all_users`) |
| `outreach.py` | Batch outreach tool: reads contact list from OneDrive folder, drafts personalized emails. **NOT a section** — on-demand tool. | server route `/api/outreach/run`, bot tool `run_outreach` |

---

## 5. Top-level `src/*.py`

### `server.py` (1879 lines) — FastAPI heart
- All HTTP routes (40+ endpoints — see §8)
- `_SECTION_RUNNERS` dict — maps section_id → run() callable
- `_format_section_for_teams(result)` — converts each section's items into a Markdown push message
- `_send_to_bot(uid, result)` — wraps formatter + sends to Teams via Audrey bot account
- `_run_section_for_user(uid, sid)` — direct (non-HTTP) runner used by bot
- Scheduler setup (`@app.on_event("startup")`)
- Per-user background workers: CRM refresh, projects refresh, email monitor, expense scan, Teams bot poll

### `bot.py` (966 lines) — Teams agent
- `SECTION_IDS` dict — catalog of sections the bot knows about (must be kept in sync with `_SECTION_RUNNERS`)
- `build_agent_response()` — constructs system prompt + tool list, sends to Gemini, handles tool calls
- ~25 tool functions: query (emails / meetings / contacts), mutate (CRM update, dismiss, snooze), trigger (`run_skill`), read/write instruction (`update_skill_instruction`), draft email, calendar event, outreach
- Conversation history kept in SQLite (`bot.sqlite`)
- LangGraph-style state for pending drafts / expenses / meeting drafts

### `ai.py` (144 lines) — Gemini wrapper
- `AIClient.generate()` — text generation with retry
- `.generate_with_search()` — Google Search grounding (for market/company intel)
- `.transcribe_audio()` / `.transcribe_video()` — Files API uploads for M03 meetings
- `.extract_json()` — JSON-only generation
- Model: `gemini-2.5-flash`

### `auth.py` (262 lines) — MSAL OAuth
- Web auth code flow + device code flow (for local dev)
- JWT session cookies (7-day, httponly)
- Per-user token storage at `.data/_sessions/{user_id}.json`
- `get_valid_access_token(uid)` — auto-refresh on expiry
- First-login triggers `_run_init_scan` (CRM + projects + profile draft)

### `graph.py` (498 lines) — Microsoft Graph client
- `GraphClient(token)` — wraps `requests` + standardised error handling
- Email: `get_messages`, `get_inbox_metadata_since`, `get_sent_messages_since`, `get_inbox_conv_since`, `get_flagged_messages`
- Calendar: `get_calendar_view`, `get_events`, `create_event`
- OneDrive: `list_drive_folder`, `search_drive`, `download_drive_item`, `upload_to_onedrive`, `ensure_folder_path`, `get_shared_recordings`
- Mail send: `create_draft`, `send_mail`, `delete_message`
- Teams chat: `find_chat_with_user`, `get_chat_messages`, `send_chat_message`, `send_html_message`
- To-Do tasks: `_get_default_todo_list_id`, `create_todo_task`
- Online meetings: `get_online_meetings`

### `slash.py` (594 lines) — Slash command handler
- Runs **before** the agent loop when message starts with `/`
- Commands: `/help`, `/context [slug] [instruction]`, `/settings`
- Slug names: `business_profile`, `writing_style`, `market_segments`
- Used to inspect or refine the profile documents from chat

### `tools.py` (335 lines) — Legacy atomic tools
- `get_upcoming_meetings`, plus other Graph query helpers
- Predates the current `bot.py` agent tools; some bot tools still reuse helpers from here
- Safe to consult, but new bot tools should live in `bot.py`

---

## 6. Skills / Instructions Architecture

Three file types orchestrate per-section AI behavior:

```
src/skills/{section_id}/
├── skill.md         ← system-level: what the section is, default keep/drop rules
└── validator.md     ← (optional) extra validator rules layered on top of skill.md

.data/{uid}/instructions/
└── {section_id}.md  ← per-user: free-form prompt, HIGHEST priority
```

**At runtime, the section calls `validate_output(items, ai, section_id, user_instruction, ...)`:**

1. Loads `skills/{sid}/skill.md` → "section purpose"
2. Loads `skills/{sid}/validator.md` if present → "validator rules"
3. Loads `instructions/{sid}.md` → "user override" (highest priority)
4. Sends all three + items list to AI
5. AI returns keep/drop/priority decisions per item
6. Failure mode: validator errors → return original items (fail-safe)

**Reference implementation:** `src/sections/relationship_health.py` (cleanest example).

---

## 7. Scheduler Jobs (`src/server.py::startup_event`)

| Job ID | Frequency | Function | Notes |
|--------|-----------|----------|-------|
| `teams_bot_poll` | every 10s | `_poll_teams_bot_all_users` | Polls Audrey's 1:1 chats; max_instances=1 |
| `email_monitor_poll` | every 1m | `_poll_email_monitor_all_users` | New email → Teams push; `coalesce=True` |
| `expense_scan_poll` | every 1m | `_poll_expense_scan_all_users` | Scans new email attachments for receipts; `coalesce=True` |
| `crm_daily_refresh` | cron 06:00 UTC | `_refresh_crm_all_users` | Incremental CRM update for every user |
| `projects_daily_refresh` | cron 06:30 UTC | `_refresh_projects_all_users` | Incremental projects update |

**Not yet wired (planned):** per-user morning brief at user-configured time (would read `.data/{uid}/schedules.json`).

---

## 8. API Routes (key)

Grouped by business area. All cookies-based auth except `/auth/*`.

### Auth (web + device code)
- `GET /auth/login`, `GET /auth/callback`, `GET /auth/logout` — web OAuth flow
- `POST /api/auth/start`, `POST /api/auth/poll` — device-code flow for local dev / bot
- `GET /api/auth/me`, `GET /api/auth/status` — current session info

### Sections (generic)
- `GET  /api/sections/{section_id}` — read cached result file
- `POST /api/sections/{section_id}/run` — trigger background run + Teams push when done
- `GET  /api/sections/{section_id}/instructions` — read user prompt
- `PUT  /api/sections/{section_id}/instructions` — write user prompt
- `GET  /api/sections/due_today` — special real-time computed endpoint (predates the section runner)

### CRM
- `GET  /api/crm` — list all contacts
- `PATCH /api/crm/{email}` — update a field on a contact (status / priority / notes / ignore)
- `POST /api/crm/scan` — trigger full rebuild

### Projects
- (Build/refresh triggered by scheduler; no direct route. Read via `/api/sections/project_status` etc.)

### Profile (user's business context)
- `GET  /api/profile` — current business_profile + market_segments
- `POST /api/profile/business` — save business_profile.md
- `POST /api/profile/segments` — save market_segments.md
- `GET  /api/profile/status` — onboarding lifecycle state
- `POST /api/profile/confirm` — mark draft as user-confirmed
- `POST /api/profile/regenerate` — re-run profile_init AI generation

### Settings (single JSON blob per user)
- `GET  /api/settings`
- `PATCH /api/settings`

### Teams bot binding
- `GET  /api/teams/bot` — current bot binding status for this user
- `POST /api/teams/bot/auth-start`, `auth-poll` — device-code flow for bot account
- `POST /api/teams/bot/activate`, `disable` — toggle bot
- Admin: `GET /api/admin/bot-bindings`, `POST /api/admin/bot/unbind/{bot_uid}`

### Domain-specific
- `POST /api/m03/scan` — trigger meeting scan
- `GET  /api/expenses/all` — full expense Excel export
- `POST /api/outreach/run` — trigger batch outreach
- `GET  /api/outreach/last` — last outreach run summary
- `GET  /api/watchlist`, `POST /api/watchlist` — custom company watchlist for `company_intelligence`

### Diagnostics
- `GET  /health`
- `GET  /api/test/graph` — sanity-check Graph token

---

## 9. Per-user Data Layout

Everything is under `.data/{user_id}/`. Multi-user isolation is a hard invariant (CLAUDE.md principle 3).

```
.data/{user_id}/
├── settings.json               ← display_name, report_email, business_context, etc.
├── crm.json                    ← contact DB (built by crm.py)
├── projects.json               ← project DB (built by projects.py)
│
├── profile/
│   ├── business_profile.md     ← injected into AI prompts
│   ├── market_segments.md      ← same
│   └── init_status.json        ← onboarding lifecycle
│
├── instructions/
│   ├── {section_id}.md         ← per-section user prompt (free-form)
│   └── ...                     ← one per AI-shaped section
│
├── results/
│   ├── {section_id}.json       ← latest section result (overwritten each run)
│   └── ...
│
├── wiki/                       ← Meeting DB
│   ├── _index.json
│   ├── {meeting_id}.json
│   └── transcripts/
│
├── expenses/
│   ├── _seen.json              ← dedup by msg_id::att_name
│   ├── _receipt_hashes.json    ← dedup by sha256 of file bytes
│   └── expenses_master.xlsx    ← cumulative receipt log
│
├── outreach/                   ← Outreach tool outputs
├── commitments_cache.json      ← incremental email→commitments cache
├── commitments_state.json      ← done / asked / snoozed
├── business_insights_history.json ← weekly snapshots (last 4)
├── market_intel_seen.json      ← 7-day dedup for market signals
├── company_intel_seen.json     ← 7-day dedup for company signals
├── market_watchlist.json       ← custom companies user follows
├── email_monitor.json          ← last_poll_id, digest queue
├── teams_bot.json              ← bot polling state
├── bot.sqlite                  ← LangGraph conversation memory
├── bot_history.db              ← (legacy bot chat log)
└── bot_link.json               ← bot ↔ owner mapping
```

**Sessions** (separate from user data):
```
.data/_sessions/
└── {user_id}.json              ← MSAL token cache, refresh tokens
```

---

## 10. Frontend (`frontend/src/App.tsx`)

**Single-file React app** (~1950 lines). Vite + Tailwind 4 + lucide-react + motion.

Pages (toggled by `Page` type):
- `dashboard` — section card grid
- `email` — Emails Awaiting Reply, Sent No Response, Yesterday's Recap, etc.
- `meetings` — Today's Meetings, Meeting Action Items, Recent Meetings
- `intelligence` — Market / Company intelligence
- `crm` — contact list + edit
- `expenses` — receipt list
- `settings` — display name, ignored senders, instruction.md editor per section
- `onboarding` — first-login profile review

Backend API calls go through `/api/*` (Vite proxy to `:8000`).

**Build:**
```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
npm run build  # production bundle
npm run lint   # tsc --noEmit
```

---

## 11. v1 Leftovers (kept on purpose)

These files were brought forward from v1 and not deleted:

| Path | Status | Why kept |
|------|--------|----------|
| `src/skills/m03_meeting/` | v1 leftover | User explicitly asked to keep. Possibly referenced by m03_meeting.py for skill text. |
| `src/modules/m03_meeting.py` | Active | Meeting intelligence pipeline is still the v1 implementation (mp4 → transcript → AI). Works fine. |
| `src/modules/m05_expense.py` | Compatibility shim | Re-exports from `src/sections/expenses.py` so older imports (e.g. `teams_bot.py`) don't break. |
| `src/tools.py` | Active | Atomic Graph tools predating the current bot agent. Some still reused by bot.py. |

**Section runner conflict:**
`GET /api/sections/due_today` is registered BEFORE the generic `GET /api/sections/{section_id}`, so it computes due_today live from `commitments_extract.json` instead of reading the snapshot. The new `due_today` section runner (added 2026-05-23) writes its own snapshot for Teams push, but the legacy live-GET endpoint still wins for HTTP GET. Acceptable for now; deduplicate later if confusing.

---

## 12. Where to make changes (quick reference)

**Add a new section** → 5 files:
1. `src/sections/{new_id}.py` — implement `run(graph, ai, data_dir, settings, progress) -> dict`
2. `src/skills/{new_id}/skill.md` — system prompt
3. `src/server.py` — add to `_SECTION_RUNNERS` + `_format_section_for_teams`
4. `src/bot.py` — add to `SECTION_IDS`
5. `src/modules/validator.py` — add to `_SECTION_TITLES` + add formatter in `_format_items_for_review`

**Change AI behavior of a section (system-wide)** → `src/skills/{id}/skill.md`
**Change AI behavior per user** → `.data/{uid}/instructions/{id}.md` (write via frontend or bot tool)

**Add a Graph API call** → `src/graph.py`
**Add a scheduler job** → `src/server.py::startup_event`
**Add a bot tool** → `src/bot.py` (inside `build_agent_response`, then add to `tools=[...]` list)
**Add a frontend page** → `frontend/src/App.tsx` (add to `Page` union + render branch)

---

## 13. Conventions (from CLAUDE.md)

1. **One section, one data source, one result file** — no fallback paths
2. **Multi-user isolation from line 1** — every function takes `data_dir: Path`
3. **Screener always before email AI** — except `expenses` (attachments, not content)
4. **Wiki only serves meeting modules** — not a generic fallback
5. **Standard result shape** — `{id, status, last_run, items, count, empty}`
6. **Calendar via `get_calendar_view()`** — never `get_events(filter=...)`
7. **Teams Adaptive Cards** — never `{"type":"Separator"}`; use `"separator":true` on next element
8. **Draft emails stay in Drafts folder** — never auto-send
