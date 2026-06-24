---
title: Document Capture (Expenses)
describes_files:
  - src/sections/expenses.py
  - src/modules/m05_expense.py
derived_from_commit: 617a540
last_synced: 2026-06-24
---

# Document Capture (Expenses)

Turns receipts, invoices, and contracts into structured records — and receipts into
a reimbursable Excel ledger.

## How it works (`expenses`)
Scans for documents, classifies each with Gemini vision into one of three types,
and extracts the right fields:
- **receipt** (already paid) → vendor / amount / GST → **appended to
  `expenses_master.xlsx`** for reimbursement.
- **invoice** (bill to pay) → vendor / amount / due_date → **not** in Excel; shown
  in the UI.
- **contract** (legal agreement) → counterparty / subject → **not** in Excel; shown
  in the UI.

All types land in the `expenses` result with a `document_type` field.

- **Sources:** (1) **email attachments** (PDF/image, fetched via
  `hasAttachments eq true`); (2) **Teams images** sent to the bot; (3) a watched
  **OneDrive folder** (sources 2 & 3 rolling out per the roadmap).
- **No screener:** expenses bypasses the email screener on purpose — the question
  is "is this attachment a receipt?", which only Gemini-vision can answer from the
  file, not from email metadata.
- **De-dup:** by `source_type + source_id + attachment_name` (+ a sha256 hash of
  the file bytes) so the same receipt is never entered twice.

> `src/modules/m05_expense.py` is a compatibility shim that re-exports from
> `src/sections/expenses.py`; new logic goes in the section, not the shim.

## Common questions
- *"I forwarded a receipt but it's not in the Excel."* — Only `receipt`-classified
  docs go to Excel; invoices/contracts are shown in the UI instead.
