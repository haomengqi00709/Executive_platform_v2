# CEO Platform v2

An executive AI assistant for Microsoft 365. Connects to a CEO's mailbox + calendar + OneDrive + Teams, runs **17 sections** that turn raw data into focused, actionable views, and pushes them to a web dashboard and the user's Teams chat (via the "Audrey" bot account).

```
M365 (mail/calendar/OneDrive/Teams)  ──┐
                                       │
Gemini 2.5-Flash (text + vision + search) ──┐
                                       │   │
              ┌────────────────────────┘   │
              ▼                            ▼
       17 Sections (src/sections/) ── per-user data (.data/{uid}/)
              │
              ├──▶ Teams push  (Audrey bot)
              └──▶ Dashboard   (frontend/, React)
```

For the deep architectural map see [`CODEBASE_MAP.md`](./CODEBASE_MAP.md).
For the design principles and history see [`CLAUDE.md`](./CLAUDE.md).

---

## Quick Start

```bash
# Backend
pip install -r requirements.txt
python -m uvicorn src.server:app --reload
# → http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev
# → http://localhost:3000 (proxies /api and /auth to :8000)
```

Required env: `PROD_CLIENT_ID`, `PROD_CLIENT_SECRET`, `REDIRECT_URI`, `SESSION_SECRET`, `GEMINI_API_KEY`.

---

## What Each Section Produces

All 17 sections return a uniform envelope:

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

The `items` shape differs per section. Below is the catalog grouped by purpose, with the **most useful fields** each section exposes (these are what the frontend will render).

### Briefing

#### `ai_summary` — AI Morning Briefing
- **Output**: a multi-paragraph briefing string + structured side data
- **Key fields**: `briefing` (the prose), `events` (today's meetings), `top_emails`, `action_items`
- **Trigger**: scheduled (morning push)
- **AI**: yes · **User can prompt**: yes

---

### Email & Commitments

#### `reply_needed` — Emails Awaiting Reply
- **One item per email** the executive needs to respond to
- **Key fields**: `subject`, `from_name`, `from_email`, `received`, `priority` (high/medium/low), `reason` (1-line summary of what the email's about), `suggested_opening` (AI-drafted reply opener), `contact` (CRM enrichment), `projects` (related projects)
- **Use case**: triage queue, deep card with reply assist
- **AI**: yes · **User can prompt**: yes

#### `followup_needed` — Sent — No Response
- **One item per sent email** that has no reply yet
- **Key fields**: `subject`, `to_name`, `to_email`, `sent`, `days_waiting`, `urgency` (high/medium/low), `reason`, `preview`
- **Use case**: "who am I waiting on" list
- **AI**: yes · **User can prompt**: yes

#### `commitments_extract` — Commitments (raw)
- **One item per promise/deadline** extracted from inbox
- **Key fields**: `description`, `type` (`my_commitment` / `their_commitment`), `due_date`, `due_date_confidence` (`explicit`/`implied`/`none`), `contact_name`, `priority`, `subject` (source email), `received`
- **Use case**: master commitment list; data source for `due_today` and `upcoming_commitments`
- **AI**: yes · **User can prompt**: yes

#### `upcoming_commitments` — Upcoming Commitments
- **Filtered view** of `commitments_extract`: due in next 7 days OR already overdue
- **Adds**: `overdue` boolean, `source` field
- **Use case**: "what's coming up" widget
- **AI**: no (pure filter) · **User can prompt**: no (Teams suppressed; frontend reads directly)

#### `due_today` — Due Today
- **Filtered view** of `commitments_extract`: `due_date == today` AND `my_commitment`
- **Use case**: morning "today's must-do" list
- **AI**: validator only · **User can prompt**: yes

#### `yesterday_recap` — Yesterday's Recap
- **Mixed-type items**: inbound emails, outbound emails, meetings, new commitments
- **Key fields**: `type` (`inbound_email`/`outbound_email`/`meeting`/`commitment`), plus type-specific fields (`subject`/`from`/`to`/`time`/`description`/`due_date`)
- **Also**: `stats` block (`inbound_count`, `outbound_count`, `meetings_count`, `commitments_count`)
- **Use case**: morning catch-up
- **AI**: validator only · **User can prompt**: yes

---

### Meetings

#### `meetings_today` — Today's Meetings
- **One item per calendar event** today
- **Key fields**: `subject`, `start_time`, `end_time`, `is_all_day`, `location`, `attendees` (list), `attendee_count`, `body_preview`
- **Use case**: agenda at a glance
- **AI**: validator only · **User can prompt**: yes

#### `recent_meetings` — Recent Meetings
- **One item per recorded meeting** with transcript + AI summary
- **Key fields**: `meeting_id`, `title`, `date`, `attendees`, `summary` (2-5 sentence AI summary), `decisions`, `key_topics`
- **Source**: OneDrive `.mp4` → transcript → AI extraction
- **AI**: yes (transcript extraction, pre-computed) · **User can prompt**: no (display only)

#### `meeting_action_items` — Meeting Action Items
- **One item per action item** extracted from a meeting
- **Key fields**: `owner`, `action`, `due_date`, `meeting_id`, `meeting_title`, `meeting_date`, `project_id`
- **Use case**: cross-meeting action queue
- **AI**: pre-computed at meeting ingest · **User can prompt**: no

---

### Projects

#### `project_status` — Project Status
- **Portfolio view**: all active projects
- **Key fields**: `name`, `category` (`client_deal`/`internal`/`vendor`/`partnership`/`other`), `status` (`ongoing`/`needs_attention`/`paused`/`early_stage`), `momentum` (`accelerating`/`steady`/`slowing`/`stalled`), `summary`, `last_activity`, `deadline`, `participant_count`, `thread_count`
- **Also**: top-level `status_counts` dict (e.g. `{"ongoing": 13, "needs_attention": 2}`)
- **Use case**: dashboard portfolio grid
- **AI**: validator only · **User can prompt**: yes (e.g. "skip internal projects")

#### `projects_needing_attention` — Projects Needing Attention
- **Filtered view**: only `needs_attention` + `early_stage` projects
- **Adds**: `next_action`, `participants` (top 8 emails), `priority` (high/medium)
- **Use case**: "weekly review" prompt
- **AI**: validator only · **User can prompt**: yes

---

### Intelligence (external)

#### `market_intelligence` — Market Intelligence
- **One item per macro market signal** (regulations, funding, M&A, tech trends)
- **Key fields**: `headline`, `summary`, `signal_type` (`regulatory`/`funding`/`M&A`/`technology`/`competitive`/`macro`/`other`), `source`, `source_url`, `published_date`, `relevance` (why this matters), `priority`
- **Source**: Gemini Google Search grounding, ~14-day window, 7-day dedup
- **AI**: yes (search + extract + validator) · **User can prompt**: yes

#### `company_intelligence` — Company Intelligence
- **One item per signal** on a tracked company (CRM clients + project participants + watchlist)
- **Key fields**: `company`, `headline`, `summary`, `signal_type` (`executive_statement`/`announcement`/`leadership`/`funding`/`M&A`/`other`), `person`, `source` (LinkedIn/X/News/Press), `source_url`, `published_date`, `relevance`, `priority`
- **Source**: per-company Gemini Search batches (general news + LinkedIn/X social pass), 7-day dedup
- **AI**: yes · **User can prompt**: yes

---

### Insights & Relationships

#### `relationship_health` — Relationship Health
- **One item per contact** whose engagement pattern is concerning
- **Key fields**: `contact_email`, `contact_name`, `company`, `status` (CRM), `health` (`at_risk`/`cooling`/`stalled`/`new` — rule-determined, healthy contacts not surfaced), `priority`, `metrics` block (`emails_in_30d`, `emails_in_prev_30d`, `trend_pct`, `last_inbound`, `days_since_inbound`, `awaiting_my_reply`), `related_projects`, `reminder` (1-2 sentence AI explanation), `suggested_action` (concrete next step)
- **Use case**: "who's gone quiet"
- **AI**: rule-based detection + AI writes reminders · **User can prompt**: yes

#### `business_insights` — Weekly Brief
- **Output**: 3-5 sentence executive `narrative` + structured `stats` (with deltas vs last week) + 3-7 `items` (categorized headlines)
- **Stats block**: `this_week`, `prev_week`, `deltas` with `current/previous/delta/pct` per metric
- **Items**: `category` (`pipeline`/`engagement`/`execution`/`intel`), `title`, `detail`, `priority`, `evidence` (which sections this draws from)
- **Source**: aggregates all other section results (meta-section)
- **AI**: aggregator (rule-based) + 1 AI narrative pass · **User can prompt**: yes

---

### Documents

#### `expenses` — Document Capture (Receipts)
- **One item per receipt** captured from email attachments or Teams DMs
- **Key fields**: `vendor`, `date`, `amount`, `currency`, `gst_hst`, `net_amount`, `category` (`Travel`/`Meals`/`Software`/`Services`/`Equipment`/`Utilities`/`Other`), `confidence`, `attachment`, `email_subject`, `from`, `processed_at`
- **Also written**: cumulative `expenses_master.xlsx`
- **Trigger**: every 1 minute (auto-scan); Teams image drop also triggers
- **AI**: Gemini vision · **User can prompt**: no (deterministic extraction)

---

## How User Customization Works

Every AI-shaped section reads two files at runtime:

```
src/skills/{section_id}/skill.md            ← system prompt (shared, defines section behavior)
.data/{uid}/instructions/{section_id}.md    ← per-user prompt (free-form, highest priority)
```

The user can edit `instructions/{section_id}.md` via:

1. **Frontend Settings page** — `PUT /api/sections/{section_id}/instructions`
2. **Teams chat** — say "skip Nexus Capital in Project Status" → Audrey calls `update_skill_instruction` tool → appends to file
3. **Direct file edit** — works in dev

Next time the section runs, the validator AI reads both files and honors the user prompt as highest priority (can drop items, adjust priorities, hide categories, etc.).

---

## Triggers

| Trigger type | Sections | Notes |
|---|---|---|
| **Scheduled** (user-configurable time) | `ai_summary`, `reply_needed`, `followup_needed`, `commitments_extract`, `upcoming_commitments`, `due_today`, `yesterday_recap`, `meetings_today`, `relationship_health`, `market_intelligence`, `company_intelligence`, `projects_needing_attention`, `project_status` | Per-user schedule config WIP — see [`CLAUDE.md`](./CLAUDE.md) |
| **Triggered** (event-driven) | `recent_meetings`, `meeting_action_items` (new OneDrive recording), `expenses` (new email/Teams attachment), `email_monitor` (new inbox email) | Auto-runs on detected events |
| **Live** (computed on read) | `meetings_today` (re-fetches calendar each call) | No cache |
| **Weekly** | `business_insights` | Aggregates the week |

Scheduler runs at server startup. See [`CODEBASE_MAP.md` §7](./CODEBASE_MAP.md#7-scheduler-jobs-srcserverpystartup_event) for the full cron list.

---

## Where the Data Lives

```
.data/{user_id}/
├── settings.json                    ← display_name, ignored senders, business_context
├── crm.json                         ← contact database (status: client/prospect/partner/...)
├── projects.json                    ← project database (status + momentum)
├── profile/business_profile.md      ← company profile (AI prompt context)
├── profile/market_segments.md       ← market segments (AI prompt context)
├── instructions/{section_id}.md     ← per-section user prompts
├── results/{section_id}.json        ← latest section output (overwritten each run)
├── wiki/                            ← meeting DB (transcripts + summaries)
├── expenses/expenses_master.xlsx    ← cumulative receipts
└── ...                              ← see CODEBASE_MAP.md §9 for full list
```

Per-user isolation is a hard invariant. Sessions live separately in `.data/_sessions/{user_id}.json`.

---

## Frontend

`frontend/src/App.tsx` is a single-file React app (~1950 lines) using Vite + Tailwind 4 + lucide-react. Pages: dashboard / email / meetings / intelligence / crm / expenses / settings / onboarding.

Backend API calls go through `/api/*` (Vite proxy to `:8000`).

A redesign is planned to organize the dashboard by the 4 mockup categories:
- **BRIEFING** (ai_summary)
- **EMAIL** (reply_needed, followup_needed, upcoming_commitments, yesterday_recap, due_today, invoices_contracts)
- **MEETINGS** (meetings_today, meeting_action_items, recent_meetings)
- **PROJECTS** (projects_needing_attention, project_status)

…with the intelligence and weekly sections (market_intelligence, company_intelligence, relationship_health, business_insights, expenses) accessible from secondary navigation.

---

## Conventions

1. One section, one data source, one result file — no fallback paths
2. Multi-user isolation from line 1 — every function takes `data_dir: Path`
3. Screener always before email AI (except `expenses`)
4. Standard result shape — `{id, status, last_run, items, count, empty}`
5. Calendar via `get_calendar_view()` — never `get_events(filter=...)`
6. Teams Adaptive Cards — never `{"type":"Separator"}`; use `"separator":true` on next element
7. Draft emails stay in Drafts folder — never auto-send

---

## Tests

```bash
pytest tests/ -v               # unit tests (mocked Gemini)
python test_screener.py        # integration: needs real M365 + Gemini
python test_m03.py             # meeting transcript pipeline
python test_bot.py             # Teams bot loop
```

Integration scripts in `test_scripts/` are ad-hoc runners.

---

## Status (as of 2026-05-23)

- 17 sections implemented and registered ✅
- All AI-shaped sections honor per-user `instructions/{section_id}.md` ✅
- CRM + projects auto-refresh daily, AI-classified ✅
- Teams bot can update instructions and trigger sections from chat ✅
- Frontend uses real backend (some pages still need redesign per mockup) 🚧
- Per-user morning brief schedule configurator 🚧
- `meeting_prep` (pre-meeting trigger section) 🚧
- `invoices_contracts` (separate work stream) 🚧
