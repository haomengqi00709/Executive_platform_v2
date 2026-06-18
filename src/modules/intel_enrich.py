"""
intel_enrich — per-item enrichment second-pass for the intelligence sections.

Adapted from Horizon's ai/enricher.py (concept → web search → synthesize), but
trimmed for our use: English-only, and applied ONLY to the top-N items (cost
control). For each selected item it produces:
  - background        2-3 sentences of context a busy CEO needs
  - community_view    how analysts / the market are reacting (if the results show it)
  - references[]      {title, url} corroborating links

Why ddgs (DuckDuckGo) and not Gemini grounding: ddgs hands back a concrete set of
real result URLs, and we let the AI cite ONLY from that set (Horizon's
anti-hallucination trick). That is what gives us guaranteed-real reference links —
the exact thing our grounding `source_url` sometimes can't (its vertex redirects
degrade to a google.com/search fallback). Citations are validated against the
returned URL set, then hardened through url_utils.resolve_source_url.

Degrades gracefully: if ddgs returns nothing (rate-limited) or a call fails, the
item simply keeps empty enrichment fields — it is never dropped and we never
fabricate a source.
"""
import json

from src.ai import AIClient
from src.modules.url_utils import resolve_source_url

DEFAULT_TOP_N = 8
_MAX_QUERIES = 2
_RESULTS_PER_QUERY = 3


def _noop(_msg: str) -> None:
    pass


def _extract_queries(item: dict, ai: AIClient) -> list[str]:
    """1-2 web-search queries that would surface corroboration + background for
    this item. Falls back to the headline if the AI step fails."""
    prompt = f"""Given this market-intelligence item, return 1-2 web search queries that would surface
corroborating coverage and useful background. Focus on the specific companies, people, events,
regulations, products, or terms named — not generic phrases.

Headline: {item.get('headline','')}
Summary: {item.get('summary','')}

Return ONLY JSON: {{"queries": ["<query 1>", "<query 2>"]}}"""
    try:
        result = json.loads(ai.extract_json(prompt))
        queries = result.get("queries") if isinstance(result, dict) else None
        if isinstance(queries, list):
            cleaned = [str(q).strip() for q in queries if str(q).strip()]
            if cleaned:
                return cleaned[:_MAX_QUERIES]
    except Exception:
        pass
    headline = (item.get("headline") or "").strip()
    return [headline] if headline else []


def _web_search(query: str) -> list[dict]:
    """DuckDuckGo search → [{title, url, body}]. Empty list on any failure."""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=_RESULTS_PER_QUERY)
    except Exception:
        return []
    out = []
    for r in (results or []):
        url = r.get("href") or r.get("url") or ""
        if url:
            out.append({"title": r.get("title", ""), "url": url, "body": r.get("body", "")})
    return out


def _synthesize(item: dict, web: list[dict], ai: AIClient, display_name: str) -> dict | None:
    """Ask the AI to write background + community_view and cite ONLY from `web`.
    Returns None on failure."""
    available = {r["url"]: r["title"] for r in web if r.get("url")}
    lines = [f"- [{r['title']}]({r['url']}): {r['body']}" for r in web]
    web_context = "\n".join(lines)
    prompt = f"""You are briefing {display_name}, a busy executive. Using ONLY the web search results
below (do not use outside knowledge, do not fabricate), write a structured analysis of this item.

Item:
- Headline: {item.get('headline','')}
- Summary: {item.get('summary','')}

Web search results:
{web_context}

Return ONLY JSON:
{{
  "background": "<2-3 sentences of context a busy CEO needs to understand this; empty string if the results add nothing>",
  "community_view": "<1-2 sentences on how analysts / the market / commentators are reacting, ONLY if the results show it; else empty string>",
  "sources": ["<url>", "..."]  // 1-3 URLs you actually used, copied VERBATIM from the results above
}}"""
    try:
        result = json.loads(ai.extract_json(prompt))
        if not isinstance(result, dict):
            return None
    except Exception:
        return None

    references = []
    seen = set()
    for u in (result.get("sources") or []):
        if u in available and u not in seen:
            final, status = resolve_source_url(u, headline=available[u])
            if final and status != "empty":
                references.append({"title": available[u], "url": final})
                seen.add(u)
    return {
        "background": str(result.get("background") or "")[:600],
        "community_view": str(result.get("community_view") or "")[:400],
        "references": references,
    }


def enrich_items(
    items: list[dict],
    ai: AIClient,
    top_n: int = DEFAULT_TOP_N,
    display_name: str = "the executive",
    log=None,
) -> list[dict]:
    """Enrich the first `top_n` items in place (they arrive sorted by score, so
    these are the highest-priority). Lower items are left untouched. Always
    returns the full list."""
    log = log or _noop
    if not items:
        return items

    targets = items[:top_n]
    log(f"enriching top {len(targets)} of {len(items)} items")
    enriched = 0
    for item in targets:
        try:
            queries = _extract_queries(item, ai)
            web: list[dict] = []
            for q in queries:
                web.extend(_web_search(q))
            if not web:
                # No external corroboration available → leave fields empty rather
                # than risk a fabricated background. The item keeps its summary.
                item.setdefault("background", "")
                item.setdefault("community_view", "")
                item.setdefault("references", [])
                continue
            result = _synthesize(item, web, ai, display_name)
            if result:
                item["background"] = result["background"]
                item["community_view"] = result["community_view"]
                item["references"] = result["references"]
                enriched += 1
            else:
                item.setdefault("background", "")
                item.setdefault("community_view", "")
                item.setdefault("references", [])
        except Exception as e:
            log(f"  enrich failed for '{item.get('headline','')[:50]}': {e}")
            item.setdefault("background", "")
            item.setdefault("community_view", "")
            item.setdefault("references", [])

    log(f"enriched {enriched}/{len(targets)} items with web-grounded background")
    return items
