---
action: false
routing: "'show me the original email', 'open the email this commitment came from', 'what did the full email say' — fetch the full original by email_id"
---
Fetch the FULL original email by its email_id (the canonical Graph id). Use when the user wants the
complete original message behind a commitment, a reply_needed item, or a follow-up — the cached
lists only carry a ~200-char preview. Returns subject, from, to, received, and the full body.
email_id: the canonical id, e.g. a commitment's `email_id`, a reply_needed/get_recent_emails item's `email_id`.
