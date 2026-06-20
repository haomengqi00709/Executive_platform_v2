---
action: false
---
Look up a meeting summary. Tries (a) wiki by exact meeting_id or title substring;
falls back to (b) live calendar event for unrecorded scheduled meetings (no summary).

Use when the user asks 'what was discussed in the Q3 meeting?',
'summarize my meeting with John', 'recap last week's sync'.

event_id_or_subject: Graph calendar event id (long), wiki meeting_id (ondrive_*/mock_*),
                     or any substring of the meeting title.
