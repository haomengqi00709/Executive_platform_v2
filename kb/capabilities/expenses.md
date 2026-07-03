---
title: Document Capture (Expenses)
describes_files:
  - src/sections/expenses.py
  - src/modules/expenses_store.py
  - src/modules/m05_expense.py
derived_from_commit: bd0f97d
last_synced: 2026-07-02
---

# Document Capture (Expenses)

Turns receipts, invoices, and contracts into structured records in a single SQLite
store — receipts also project out to a reimbursable Excel ledger.

## Storage: `expenses_store` (store.db)
Expenses live in the shared per-user `store.db` (same DB as commitments / CRM /
projects), in the `expenses` table — one JSON-blob row per document keyed by a
stable id `sha1("{msg_id}::{att_id}")` (identical to the frontend's row id, so ids
never move). `expenses_store.py` mirrors `projects_store.py`: lazy one-time import,
`upsert_expense` / `update_expense_fields` / `delete_expense` / `load_expenses`, and
`write_projection`.

**The store is the source of truth; two files are synced projections** (so every
legacy reader keeps working, no reader change needed):
- `expenses/expenses_master.xlsx` ← **receipts only** (the reimbursement export).
- `results/expenses.json` ← **all three types** (section route / legacy readers).

## How it works (`expenses`)
Classifies each document with Gemini vision into one of three types and stores it:
- **receipt** (already paid) → vendor / amount / GST → store **and** the Excel export.
- **invoice** (bill to pay) → vendor / amount / due_date → store only (Excel is
  receipts-only); shown in the dashboard's **Invoices** tab.
- **contract** (legal agreement) → counterparty / subject → store only; shown in the
  **Contracts** tab.

All three persist to the `expenses` table with a `document_type` field, and the
dashboard (`GET /api/expenses/all` → `ExpensesTab`) has a Receipts / Invoices /
Contracts tab bar.

- **Sources:** (1) **email attachments** (`hasAttachments eq true`); (2) **Teams
  images** sent to the bot — *all three types* now persist (previously invoices &
  contracts were acknowledged but dropped); (3) a watched **OneDrive folder**
  (roadmap).
- **No screener:** expenses bypasses the email screener on purpose — "is this
  attachment a receipt?" is a file-content question only Gemini-vision can answer.
- **De-dup:** by `{msg_id}::{att_name}` (+ a sha256 hash of the bytes). The email
  scan uses the `expenses_seen` table; the Teams path keeps its own `_seen.json` /
  `_receipt_hashes.json` caches (independent attachment streams).

## Attachments are a first-class agent input
When a file arrives in Teams, the bot auto-captures it (receipt/invoice/contract →
store; business card → CRM) **and** stores the file to OneDrive + puts a handle on
`bot_state["pending_file"]`. If the user then says "forward this to X", the agent
calls the `forward_file` tool (creates a Drafts email with the file attached —
Drafts only, never auto-sends). Bare captures with no request skip the agent (cheap).

> `src/modules/m05_expense.py` is a compatibility shim that re-exports from
> `src/sections/expenses.py`; new logic goes in the section / `expenses_store.py`.

## Common questions
- *"I sent a receipt/invoice to Audrey but it's not in the dashboard."* — All three
  types now persist to the store and appear under their tab (Receipts / Invoices /
  Contracts). Only `receipt` also goes to the reimbursement Excel.
