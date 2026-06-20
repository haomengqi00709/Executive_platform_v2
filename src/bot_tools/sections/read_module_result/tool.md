---
action: false
---
Read the latest cached result for a section. If the result contains an
`items` list, each item gets a 1-based `index` field added so the user can
refer to items by #N. Canonical IDs (email_id / id / project_id …) stay on
each item so you can call action tools with them.

section_id must be one of: ai_summary, market_intelligence, company_intelligence,
reply_needed, followup_needed, commitments_extract, upcoming_commitments,
recent_meetings, meeting_action_items, relationship_health, business_insights, expenses
