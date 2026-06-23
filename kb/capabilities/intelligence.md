---
title: Market & Business Intelligence
describes_files:
  - src/sections/market_intelligence.py
  - src/sections/company_intelligence.py
  - src/sections/business_insights.py
  - src/skills/market_intelligence/skill.md
  - src/skills/company_intelligence/skill.md
  - src/skills/business_insights/skill.md
  - src/modules/profile.py
  - src/modules/intel_enrich.py
  - src/modules/intel_dedup.py
derived_from_commit: 331a41b
last_synced: 2026-06-22
volatile_pointers:
  - src/skills/market_intelligence/skill.md
  - src/skills/company_intelligence/skill.md
  - src/skills/business_insights/skill.md
---

# Market & Business Intelligence

External-facing and aggregate intelligence about the executive's market.

## Market Intelligence (`market_intelligence`)
A daily brief of real, on-instruction market signals (new projects, tenders, awards,
expansions, safety / as-built work, competitor and digital-transformation moves). The
user's own per-user instruction (`instructions/market_intelligence.md`) is authoritative:
it sets the geographies, industries, focus areas and priority order. Search COMBINES two inputs
via `get_market_config()`: the user's identity as a LENS (their capability / angle, from the
profile) and their instruction as a DOMAIN (the market to watch). In the default `intersect`
mode a planner crosses lens × domain into fan-out angles (e.g. an AI-advisory profile × a
water-pump instruction → "AI in water pumps"); one Gemini grounding search runs per angle, and
the per-angle prompt frames each item's relevance as applying the lens to that market, with a
clearly-secondary domain fallback when the intersection is thin. This fixes the old conflict
(injecting profile + instruction as peers forced a mismatched identity onto every item) and
keeps off-lens noise (market-size reports, stock / holding filings) out by construction;
`domain_only` mode (or no lens) reverts to a plain domain fan-out. A single grounding call is
one stochastic slice, so fan-out + permanent dedup build coverage over time. There is no fixed
topic taxonomy or hardcoded search window (an earlier 3-generic-bucket + "last 14 days"
construction overrode the instruction and was removed). Candidates are ranked by relevance and
capped to the top ~12, and a hard recency filter drops items older than the user's configured
window (`settings.market_intel_recency_days`, default 30 days). Only specific events surface.
`get_market_config` (domain / lens / combine_mode / rules) is a single file-backed accessor —
the contract a future SQLite store will back without changing the search logic.
- **Data source:** Gemini search grounding, scoped by the user's instruction + business
  profile / market segments (`src/modules/profile.py`). Optional per-user feeds add extra
  sources, off by default.
- **Enrichment (top items):** `intel_enrich` grounds a background per top item via Gemini
  Google-Search grounding (NOT ddgs — ddgs is intermittently blocked on datacenter IPs, which
  left backgrounds empty on Railway), attaching the real cited sources (`grounding_chunks`,
  resolved; vertex-redirect / google-search fallbacks dropped, also from `source_url`).
  Best-effort deep read: a resolved reference's full article is fetched (httpx) and the
  background rewritten from it; paywalled / unfetchable pages keep the grounded background, so
  a background is essentially never empty. Shared with Company Intelligence.

## Company Intelligence (`company_intelligence`)
News and signals about specific companies the user has chosen to watch.
- **Data source:** CRM + projects + a custom watchlist + Gemini search.

## Business Insights (`business_insights`)
A weekly business brief: a narrative plus structured stats (deltas vs prior week)
and key items by category (pipeline / engagement / execution / intel).
- **Data source:** aggregates other sections' results — it does not fetch raw data
  itself.

- **All three:** Scheduled; relevance filtering + a validator guard against
  irrelevant or fabricated signals. Dedup is two-layer (`intel_dedup`): an md5-exact
  layer kept PERMANENTLY (a once-surfaced item is never re-pushed) + an AI semantic
  layer bounded to 14 days (token cost) that catches reworded repeats.

## Common questions
- *"Can I tell it which companies to watch?"* — Yes, via the watchlist
  (`/api/watchlist`); Company Intelligence reads it.
- *"Why is the news relevant to me specifically?"* — It's scoped by your Business
  Profile + Market Segments context docs.
