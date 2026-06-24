---
action: false
routing: "'show me the full original email', 'what did that email actually say', 'open the email' — ONLY to fetch the FULL verbatim body; NOT for 'where is it from' / 'what's it about' / 'who/when' (answer those from the item's own subject & date)"
---
Fetch the FULL verbatim body of an original email by its email_id. Use ONLY when the user explicitly
wants the complete original message text ("show me the full email", "what did it actually say").
Do NOT use this to answer "where is this from", "what is it about", "who sent it", or "when" — the
subject, sender, and date are ALREADY on the commitment / reply_needed / follow-up item in front of
you; answer those directly from that data, with no fetch. Returns subject, from, to, received, and the
full body (the cached lists only carry a ~200-char preview).
email_id: the email's canonical id; you may also pass a commitment's id (resolved to its source email).
