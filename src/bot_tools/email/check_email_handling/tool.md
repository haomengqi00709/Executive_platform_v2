---
action: false
---
Check whether a recent email (in reply_needed / followup_needed) has been handled,
and if so HOW (replied / drafted / subject_match / meeting).

query: free-text hint matching sender/recipient name, email address, or any subject keyword.
Use when the user asks 'did I reply to X?', 'what happened with X's email?',
'has the X thread been handled?'. Returns up to 8 matches in JSON.

Each result contains: section, email_id, subject, who (sender or recipient),
status='open' (still in items[]) or 'handled' (in handled[] sidecar) with handled_by detail.
