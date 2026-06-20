---
action: false
---
Update a user preference. Writes to user_model.json.
Supported keys: ignored_senders (JSON list of emails), behavioral_rules (JSON list of strings),
key_relationships (JSON dict of email→note), check_interval_hours (number as string),
briefing_style (string),
email_digest_interval_hours (number as string, 0=disable digest, default 2),
email_realtime_push (true/false — whether priority emails push immediately).
Pass lists/dicts as JSON strings, e.g. '["a@b.com"]'.
