---
action: true
---
Create a calendar event in the user's Outlook calendar.
day: the day the user named, AS A WORD — 'today', 'tomorrow', 'friday', 'next friday',
  or an absolute 'YYYY-MM-DD'. ALWAYS pass this; the system resolves the actual date from
  the user's current local date, so you must NOT do date arithmetic yourself.
start_iso: ISO 8601 carrying the TIME of day (the date part is ignored when `day` is set),
  e.g. '2026-01-01T17:00:00' for 5pm. Convert the natural-language time; the system takes
  the date from `day` and the time from here.
end_iso: optional; if omitted, defaults to 30 minutes after start. Set it only when
  the user gave a duration or end time. (So 'schedule X tomorrow at 5:30pm' is enough to book.)
attendee_emails: comma-separated email addresses (leave empty for solo blocks).
is_online_meeting: defaults to TRUE — every event gets a Teams meeting link so attendees
  can join online. Set it false ONLY when the user explicitly asks for an in-person /
  offline event with no online link.
