---
action: true
---
Create a calendar event in the user's Outlook calendar.
start_iso: ISO 8601 in the user's local timezone, e.g. '2026-05-30T14:00:00'
  — convert natural-language time using the timezone in your context.
end_iso: optional; if omitted, defaults to 30 minutes after start. Set it only when
  the user gave a duration or end time. (So 'schedule X at 5:30pm' is enough to book.)
attendee_emails: comma-separated email addresses (leave empty for solo blocks).
is_online_meeting: set true to add a Teams meeting link.
