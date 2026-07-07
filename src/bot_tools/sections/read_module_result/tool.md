---
action: false
---
Read the latest result for a section. If the result contains an
`items` list, each item gets a 1-based `index` field added so the user can
refer to items by #N. Canonical IDs (email_id / id / project_id …) stay on
each item so you can call action tools with them.

FRESHNESS — check the `status` field before presenting the data:
- `status: "fresh"` → current, present normally.
- `status: "stale"` → the data is from `as_of` (a past date) and may be outdated. You MUST tell
  the user it is as of that date and offer to refresh with run_skill(section_id) — NEVER present
  stale data as if it were current (e.g. do not call a stale `meetings_today`/`yesterday_recap`
  "today's"). Today's meetings are always live, so they won't be stale.
- `status: "not_run"` → the section hasn't produced results yet; offer to run it with run_skill.

section_id must be one of: ai_summary, market_intelligence, company_intelligence,
reply_needed, followup_needed, commitments_extract, upcoming_commitments,
recent_meetings, meeting_action_items, relationship_health, business_insights, expenses
