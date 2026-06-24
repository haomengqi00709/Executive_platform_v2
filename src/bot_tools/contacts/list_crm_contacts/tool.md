---
action: false
routing: "'who are my high-priority contacts', 'list my clients', 'show internal contacts', 'contacts tagged X' — list the curated CRM by status/priority/tag (NOT email volume; that's get_email_frequency_report)"
---
List CRM contacts filtered by status, priority, and/or tag — the CURATED contact database, so it
excludes inbox noise (newsletters/no-reply). Use for "my high-priority contacts", "my clients",
"internal contacts", "everyone tagged X". Combine filters (e.g. status='client' priority='high').
status ∈ client / prospect / partner / investor / vendor / internal / other.
priority ∈ high / medium / low. tag = any group label (substring match).
Leave all blank to list everyone. Each result has #N + email for follow-up actions.
