# Function-layer write audit (F2a)

Goal: confirm every bot **write/modify** tool (`IS_ACTION = True`) persists through the SQLite
store (the single source of truth) — not a direct JSON/file write that the next refresh could roll
back (the `db_cleaner` class of bug). Audited in the `bot-l2-addressing` worktree.

| Tool | Persists via | Verdict |
|---|---|---|
| `mark_commitment_done` / `snooze_commitment` / `dismiss_commitment` | `commitments_store.*` (SQLite) | ✅ store |
| `update_crm_contact` | `crm.update_contact` → `crm_store.update_contact_field` | ✅ store |
| `tag_recent_contacts` | `crm.tag_contacts_added_since` → `crm.save_crm` → `crm_store.replace_from_dict` | ✅ store |
| `dismiss_email_followup` | `email_store.mark_handled` (kind=followup_dismissed) | ✅ store |
| `approve_draft` | `owner_graph.create_draft` (Outlook) + `email_store.mark_handled` (kind=drafted) | ✅ Graph + store |
| `create_calendar_event` | `owner_graph.create_event` (Outlook calendar) | ✅ Graph (cloud) |
| `run_outreach` / `confirm_group_email` | `outreach.*` → Outlook drafts (Graph) | ✅ Graph (cloud) |
| `create_reply_draft` / `draft_group_email` / `skip_draft` / `discard_expense` / `cancel_group_email` | `ctx.state` only (in-turn staging) | ✅ no persistence |
| `confirm_expense` | Excel `expenses_master.xlsx` (m05) | ⚠️ Excel ledger — **out of store-migration scope by design** |

**Conclusion:** no bypass. Every mutation to a store-domain (commitments / email / CRM / projects)
flows through a store module's write function (→ DB + synced projection). The only non-store local
persistence is the **expenses Excel ledger**, which is intentionally a separate account book, not a
store domain. Graph-backed actions (drafts, calendar, outreach) correctly live in the cloud.

Note: an earlier exploration mis-reported `update_crm_contact` / `dismiss_email_followup` as bypasses
— that traced the **main repo** (pre-migration), not this worktree, where commits `e5a3cc1` (CRM →
store) and `a412da0` (followup dismiss → store) already routed them.
