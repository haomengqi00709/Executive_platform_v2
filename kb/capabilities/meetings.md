---
title: Meeting Intelligence
describes_files:
  - src/sections/meetings_today.py
  - src/sections/recent_meetings.py
  - src/sections/meeting_action_items.py
  - src/sections/meeting_prep.py
  - src/modules/m03_meeting.py
  - src/modules/wiki.py
  - src/skills/meetings_today/skill.md
  - src/skills/m03_meeting/skill.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/meetings_today/skill.md
---

# Meeting Intelligence

Everything around meetings: what's on today, prep, and post-meeting recordings.

## Today's Meetings (`meetings_today`)
Today's calendar with attendees and join links.
- **Data source:** Graph `calendarView` (live; always `get_calendar_view()`, never
  `get_events(filter=...)`).

## Meeting Prep (`meeting_prep`)
Pre-meeting briefing for upcoming meetings — context on attendees/topics.

## Recordings → summaries (the M03 pipeline)
When a meeting recording (`.mp4`) lands in OneDrive, `m03_meeting.py` runs:
transcription (VTT / audio / video chain via Gemini) → AI extracts summary,
decisions, and action items → stored in the **Meeting DB**.

- **Recent Meetings (`recent_meetings`)** — displays those summaries/decisions/
  actions. Read-only.
- **Meeting Action Items (`meeting_action_items`)** — action items rolled up
  across recent meetings. Read-only.
- **Trigger:** event-driven (new recording). The **Meeting Autoresponder** can
  auto-summarize, push to Teams, and draft a follow-up email to Outlook Drafts.

## The "Meeting DB" (a.k.a. the `wiki/` folder — legacy name)
The meeting store is `src/modules/wiki.py`, persisting to `.data/{uid}/wiki/`
(`_index.json` + `{meeting_id}.json` + transcripts). **Despite the folder name it
is NOT a wiki — it's a JSON meeting database**, and it serves *only* the meeting
sections (it is never a fallback data source for anything else). This KB you're
reading is a separate thing; do not confuse the two.

## Common questions
- *"Why didn't my meeting get summarized?"* — The recording must be an `.mp4` in
  the watched OneDrive location; already-processed files are skipped via
  `wiki/_index.json`.
