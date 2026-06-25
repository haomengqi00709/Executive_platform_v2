---
action: false
routing: "'what companies am I tracking', 'which companies am I monitoring for intelligence', 'list my companies', 'what companies am I watching' — list the company database"
---
List the companies in the user's company database (auto-derived from CRM contacts + Projects by email
domain, plus any the user added manually). Use for "what companies am I tracking / monitoring for
intelligence", "list my companies", "which companies am I watching".
only_monitored (default true): show only the companies that Company Intelligence actually runs on
  (monitor toggle on, not ignored, and a client/prospect/partner/investor or manually added). Set
  false to list ALL companies, including vendors/noise.
status: filter by derived status (client / prospect / partner / investor / vendor / internal / other).
priority: filter by user priority (high / medium / low).
Each result has #N + key for follow-up.
