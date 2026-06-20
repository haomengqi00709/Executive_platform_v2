---
action: true
---
Compose an email draft and STAGE it for the user to review in Teams — it is
NOT saved to Outlook yet. ALWAYS compose your best version from context (the
thread, writing style, the user's stated intent) right away — do NOT ask 'what
should it say'; the user refines after seeing it. Call this whenever the user
asks to draft, write, compose, OR REVISE an email; to revise, call it AGAIN with the updated
subject/body and it re-stages the new version (there is no 'editing a saved
draft' — you simply re-compose).
to: recipient email address
subject: subject line (prefix 'Re: ' for replies)
body: body in the user's writing style — do NOT write a sign-off (a signature
      is appended automatically when the draft is saved).
After this returns, SHOW the user the full draft (To, Subject, and the Body
verbatim), then tell them to reply '1' (or 'save') to save it to Outlook
Drafts, or to say what to change. Do NOT claim it is saved — it is only saved
after the user confirms and approve_draft() runs.
