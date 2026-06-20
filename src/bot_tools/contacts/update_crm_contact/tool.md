---
action: true
---
Update a field on a CRM contact. Creates the contact if it doesn't exist.
Fields:
  priority    — high / medium / low / none
  notes       — free text, APPENDED with date stamp (not overwritten)
  company     — company name string
  name        — display name string
  ignore      — true / false (blocks email notifications from this sender)
Use get_contact_history first to confirm the correct email address.
