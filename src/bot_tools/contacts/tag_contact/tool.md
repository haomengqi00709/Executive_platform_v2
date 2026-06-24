---
action: true
routing: "'tag Daniel as VIP', 'add Sarah to the Investors group', 'remove X from the Y group' — add/remove a tag (group label) on ONE named contact"
---
Add or remove a tag (group label) on ONE specific contact. Use for "tag X as Y", "add X to the Y
group", "remove X from the Y group". Tags double as bulk-email groups. Existing tags are preserved
(this adds one, it doesn't replace the list). For tagging a batch of recently-added contacts at once,
use tag_recent_contacts instead.
name_or_email: the contact — a name (resolved against the CRM) or an email.
tag: the group label to apply.
remove: set true to remove the tag instead of adding it.
