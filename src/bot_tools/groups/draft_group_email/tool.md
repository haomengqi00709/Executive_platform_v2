---
action: true
---
Stage a personalized bulk email to a CRM group (a CRM tag). Does NOT
create drafts yet — it resolves the group, shows exactly who will receive
it, and waits for the user to confirm.

group:   the group/tag name the user named, e.g. 'Investors', 'Clients'.
message: what the email is about, in the user's words, e.g. 'the Q3 roadmap
         and our new pricing'. Becomes the core message of every draft.
context_note: optional extra context for the drafter (rarely needed).

Use whenever the user wants ONE message sent to a whole group/tag, however they
phrase it: 'email the X group about Y', 'draft an email to everyone in the X
group', 'message everyone in group1', 'write the Investors group about Z',
'email everyone tagged Clients'. "everyone in the X group" means the same as
"tagged X" — pass X as `group`. After calling this, relay the returned text to
the user and WAIT — do not call confirm_group_email until the user agrees.
