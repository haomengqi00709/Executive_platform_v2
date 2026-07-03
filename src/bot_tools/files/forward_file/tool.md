---
action: true
routing: forward_file — attach the file the user just sent (receipt, invoice, contract, or any document) to a NEW Outlook draft to someone. Use for "send/forward this to X", "email this to X", "attach this and send to X".
---
Forward the most recently received file to someone as an email attachment. The file is whatever the
user last sent you in this chat — it is held for you, so you do NOT need its contents or to ask for it
again.

Parameters:
- `to`: the recipient — an email address, OR a contact name (I resolve it to their address; if it's
  ambiguous I'll ask which one). If you already know the email, pass it directly.
- `subject` (optional): email subject. Defaults to "Forwarding: <filename>".
- `note` (optional): a short body message. Defaults to a simple "please find attached" note.

This ALWAYS saves to Drafts only — it never sends. After calling it, tell the user the draft is ready
in their Drafts to review and send. Only call this when a file is actually pending; if there is none,
ask the user to send the file first.
