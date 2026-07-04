# KB Change Log

Append-only. One line per event. Grep recent: `grep '^## \[' kb/log.md | tail -5`.

## [2026-06-15] ingest | initial bootstrap — 11 capability + 4 architecture pages, KB_GUIDE + lint.py @46c63d6
## [2026-06-19] sync | workflow-tools — bot [#N] list convention + look-before-you-ask disambiguation + completion gate @b86951a
## [2026-06-19] sync | workflow-tools — needs_user sends agent's listed reply not verifier one-liner @e7562a3
## [2026-06-20] sync | workflow-tools — completion gate skips pure reads (relevance pre-filter) @212022c
## [2026-06-20] sync | workflow-tools — conversational draft flow: stage in Teams → refine → 1 saves to Drafts @5d17b31
## [2026-06-20] sync | workflow-tools — act-don't-ask, compound, type-matched #N, honest no-tool, empty-retry @b08e40c
## [2026-06-22] sync | intelligence — market_intelligence fan-out search (planner-derived angles) + top-N cap + per-user recency filter @ad23782
## [2026-06-22] sync | intelligence — market_intelligence drops unresolvable source_url (no google-search fallback link) @8a20893
## [2026-06-22] sync | intelligence — intel_enrich deep-reads full article text (vs snippet) for top items + drops fallback refs @c71aa4c
## [2026-06-23] sync | intelligence — market_intelligence intersection search (lens × domain via get_market_config) + permanent md5-exact dedup @502c2e9
## [2026-06-23] sync | intelligence — intel_enrich grounds backgrounds via Gemini search (drops ddgs, unreliable on datacenter IPs) @3c08c7c
## [2026-06-23] sync | intelligence — intel_enrich background prompts no longer centre on reader's name (fixes "no info about <name>" backgrounds) @331a41b
## [2026-06-23] sync | intelligence — intel_enrich backfills empty source_url from a real grounding-cited link (main search's model-reported URL often fails) @a16ce76
## [2026-06-24] sync | data-and-auth + overview — per-user store.db single source of truth (commitments/email/CRM/projects); JSONs are synced projections; lossless migration + admin verdict @617a540
## [2026-06-24] sync | commitments — store-backed; real-time extraction from new mail; their_commitment auto-clears when counterparty replies (conversation_id) @617a540
## [2026-06-24] sync | data-management + projects + relationships — CRM/projects store-backed & edit-preserving; new list_crm_contacts (status/priority/tag); enriched get_contact_history; bot modify_project; cleanup merges/archives durable @617a540
## [2026-06-24] sync | email-triage + delivery — drafted/replied overlaid out live; follow-up dismissable; email monitor extracts commitments + auto-clears in real time @617a540
## [2026-06-24] sync | workflow-tools — new tools (modify_project, open_email, list_crm_contacts); per-source #N buckets fix cross-list collision @617a540
## [2026-06-24] sync | deployment + expenses + meetings — Railway-only (Azure decommissioned); non-behavioral bumps @617a540
## [2026-06-25] sync | data-management — companies → store (Phase 3c, store-backed + edit-preserving); list_companies + tag_contact bot tools @97215fd
## [2026-06-25] sync | workflow-tools — new tools (list_companies/tag_contact); shown-list invalidated after a mutating action so #N re-resolves live @97215fd
## [2026-06-25] sync | overview + sections-framework + delivery — companies store migration (server.py); non-behavioral bumps @97215fd
## [2026-07-02] sync | expenses — migrated to store.db (expenses table, dual xlsx/json projection); Teams invoices/contracts now PERSIST (were dropped) + dashboard Receipts/Invoices/Contracts tabs; attachments are a first-class agent input (pending_file + forward_file tool, Drafts-only) @bd0f97d
## [2026-07-04] note | projects — extraction now batches by client (not recency) + timeout split-retry; page re-sync deferred with existing KB debt @pending
