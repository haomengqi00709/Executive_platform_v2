---
action: false
routing: "'do I have an email about X', 'find/search X in my email/mailbox', 'find the attachment/file X', 'find my meeting with/about X', 'what's <name>'s email' — ANY find/search/'有没有' request over the user's own data. NEVER answer these from reply_needed/followup_needed sections and NEVER run a skill/section (e.g. market intelligence) instead."
---
Search the user's OWN data — the single tool for every find/lookup request.

what: which domain to search —
  'emails'      full-mailbox search (subject + body + sender), ALL folders, no date
                limit. Use for "do I have an email about X", "find the email from Y
                about Z".
  'attachments' find emails BY ATTACHMENT file name ("find the NDA pdf someone sent me").
  'contacts'    CRM lookup by name/company/email fragment, any word order
                ("what's jason hao's email").
  'meetings'    calendar events past 180 days + next 90, matched on title/attendees.
  'files'       OneDrive file search by name/content.
query: the search words — just the distinctive keywords, not a full sentence.
days_back: optional; restrict emails to the last N days, or widen/narrow the meetings
  look-back window. Leave 0 for the default (unlimited for emails, 180d for meetings).
top: max results (default 10, max 15).

Results carry `index` (1-based) and canonical ids and are registered as the current
list — so the user can follow up with "open 2", "reply to 1", "forward 3 to X".
If the search returns nothing, say so honestly; never fabricate a result.
