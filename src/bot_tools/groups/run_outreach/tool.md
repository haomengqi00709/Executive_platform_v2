---
action: true
---
Batch-generate personalized email drafts. Three modes — use ONE:

folder       — scan a OneDrive folder for cards/csv/xlsx/pdf and draft per contact found.
               e.g. folder='Conferences/TechConf'. Empty uses settings.outreach_folder.
tag          — pull contacts from CRM tagged with this label (case-insensitive substring).
               e.g. tag='Calgary Energy Summit 2026'.
recent_hours — pull contacts from CRM added in the last N hours.
               e.g. recent_hours=24 for "contacts I added today".

context_note: brief context injected into each draft (e.g. 'met at TechConf').
              Always ask the user for this if not obvious from the conversation.

Drafts are saved to Outlook Drafts — user manually reviews and sends each one.
Note: when users send business cards in Teams chat, drafts are AUTO-generated already;
this tool is for batch operations on existing CRM contacts or OneDrive uploads.
