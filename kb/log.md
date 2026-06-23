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
