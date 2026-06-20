---
action: false
---
Read the current custom instructions for a section. Always call this BEFORE updating,
so you can append new rules rather than overwrite existing ones.

section_id must be one of:
  ai_summary           — Morning Briefing (daily summary of calendar, emails, priorities)
  market_intelligence  — Market Intelligence (industry news, competitor updates)
  company_intelligence — Company Intelligence (targeted signals on monitored companies)
  reply_needed         — Emails Awaiting Reply (inbox emails waiting for your response)
  followup_needed      — Sent — No Response (emails you sent, other party hasn't replied)
  commitments_extract  — Commitments Extracted (promises and deadlines from emails)
  upcoming_commitments — Upcoming Commitments (deadlines and commitments in next 2 weeks)
  recent_meetings      — Recent Meetings (summaries from recorded meetings)
  meeting_action_items — Meeting Action Items (open action items from meetings)
  relationship_health  — Relationship Health (health scores for key business contacts)
  business_insights    — Business Insights (AI analysis of business patterns)
  expenses             — Expense Capture (receipts and invoices)
  email_monitor        — Email Monitor Triage (rules for priority/review/skip classification)
