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
derived_from_commit: ad23782
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
it sets the geographies, industries, focus areas and priority order. The search fans out:
a planner derives angles from the user's own data (the companies named in the business
profile — clients / partners / competitors — plus the focus terms in the instruction), and
one Gemini grounding search runs per angle, then results are merged and deduped. A single
grounding call is one stochastic slice, so the fan-out is what makes client + focus coverage
reliable. There is no fixed topic taxonomy or hardcoded search window (an earlier
3-generic-bucket + "last 14 days" construction overrode the instruction and was removed).
Candidates are then ranked by relevance and capped to the top ~12, and a hard recency filter
drops items older than the user's configured window (`settings.market_intel_recency_days`,
default 30 days) — the model does not reliably honour the window on its own. Only specific
events surface — not market-size reports or explainers.
- **Data source:** Gemini search grounding, scoped by the user's instruction + business
  profile / market segments (`src/modules/profile.py`). Optional per-user feeds add extra
  sources, off by default.

## Company Intelligence (`company_intelligence`)
News and signals about specific companies the user has chosen to watch.
- **Data source:** CRM + projects + a custom watchlist + Gemini search.

## Business Insights (`business_insights`)
A weekly business brief: a narrative plus structured stats (deltas vs prior week)
and key items by category (pipeline / engagement / execution / intel).
- **Data source:** aggregates other sections' results — it does not fetch raw data
  itself.

- **All three:** Scheduled; relevance filtering + a validator guard against
  irrelevant or fabricated signals. De-dup windows prevent repeating the same
  signal day to day.

## Common questions
- *"Can I tell it which companies to watch?"* — Yes, via the watchlist
  (`/api/watchlist`); Company Intelligence reads it.
- *"Why is the news relevant to me specifically?"* — It's scoped by your Business
  Profile + Market Segments context docs.
