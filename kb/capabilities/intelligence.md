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
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/market_intelligence/skill.md
  - src/skills/company_intelligence/skill.md
  - src/skills/business_insights/skill.md
---

# Market & Business Intelligence

External-facing and aggregate intelligence about the executive's market.

## Market Intelligence (`market_intelligence`)
Industry signals (regulation, funding, M&A, tech shifts) relevant to the user's
market, retrieved via Gemini Google Search grounding and filtered for relevance.
- **Data source:** Gemini search grounding, scoped by the user's business profile /
  market segments (`src/modules/profile.py`).

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
