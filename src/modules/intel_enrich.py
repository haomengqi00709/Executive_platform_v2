"""
intel_enrich — per-item enrichment second-pass for the intelligence sections.

Adapted from Horizon's ai/enricher.py (concept → web search → synthesize), but
trimmed for our use: English-only, and applied ONLY to the top-N items (cost
control). For each selected item it produces:
  - background        2-3 sentences of context a busy CEO needs
  - references[]      {title, url} corroborating links

Why ddgs (DuckDuckGo) and not Gemini grounding: ddgs hands back a concrete set of
real result URLs, and we let the AI cite ONLY from that set (Horizon's
anti-hallucination trick). That is what gives us guaranteed-real reference links —
the exact thing our grounding `source_url` sometimes can't (its vertex redirects
degrade to a google.com/search fallback). Citations are validated against the
returned URL set, then hardened through url_utils.resolve_source_url.

Deep read: for the first few results of each item we FETCH the real article and
extract its main text, so the AI summarises from full content rather than a one-line
search snippet. Quality-checked — a paywall teaser, block page, or fetch error is
discarded and the result keeps its snippet body (so it is never worse than before).

Degrades gracefully: if ddgs returns nothing (rate-limited) or a call fails, the
item simply keeps empty enrichment fields — it is never dropped and we never
fabricate a source.
"""
import html as _html
import json
import re

import httpx

from src.ai import AIClient
from src.modules.url_utils import resolve_source_url

DEFAULT_TOP_N = 8
_MAX_QUERIES = 2
_RESULTS_PER_QUERY = 3

# Deep-read (full-article fetch) tuning
_FETCH_TIMEOUT = 5.0
_MAX_FETCH_PER_ITEM = 2
_MIN_ARTICLE_CHARS = 600       # below this → paywall teaser / block page / not an article
_MAX_ARTICLE_CHARS = 6000      # cap text fed to the AI (token control)
_UA = "Mozilla/5.0 (compatible; CEOPlatform/1.0)"
_PAYWALL_MARKERS = (
    "subscribe to read", "subscribe to continue", "subscription required",
    "create a free account", "create an account to", "sign in to read",
    "sign in to continue", "to continue reading", "subscribers only",
    "this content is for subscribers", "log in to continue", "register to continue",
    "become a member", "please enable javascript",
)


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


def _extract_main_text(raw_html: str) -> str:
    """Dependency-free main-text extraction: pull <p> paragraph text only (article bodies live
    in <p>; nav / ads / buttons / teasers don't). No full tag-strip fallback — a page with
    little <p> text is likely JS-rendered, a block page, or a paywall teaser, so we return the
    little there is and let the caller's length check fall back to the snippet (no nav junk)."""
    h = re.sub(r"(?is)<(script|style|head|noscript|svg)[^>]*>.*?</\1>", " ", raw_html)
    paras = re.findall(r"(?is)<p[\s>].*?</p>", h)
    text = " ".join(re.sub(r"(?is)<[^>]+>", " ", p) for p in paras)
    return " ".join(_html.unescape(text).split())


def _fetch_article(url: str) -> str:
    """Fetch a real article URL and return its main text, or "" if the fetch fails or the
    content looks like a paywall / block stub — the caller then keeps the search snippet.
    A paywall typically returns HTTP 200 + a short teaser, so we judge by content (length +
    paywall markers), not just the status code."""
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        with httpx.Client(follow_redirects=True, timeout=_FETCH_TIMEOUT,
                          headers={"User-Agent": _UA}) as client:
            resp = client.get(url)
    except Exception:
        return ""
    if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "").lower():
        return ""
    text = _extract_main_text(resp.text)
    if len(text) < _MIN_ARTICLE_CHARS:
        return ""  # too thin → paywall teaser / block page / not an article
    if any(m in text[:2000].lower() for m in _PAYWALL_MARKERS):
        return ""  # explicit paywall / login wall
    return text[:_MAX_ARTICLE_CHARS]


def _synthesize(item: dict, web: list[dict], ai: AIClient, display_name: str) -> dict | None:
    """Ask the AI to write a background note and cite ONLY from `web`.
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
            # Only keep references that resolve to a REAL article (resolved/kept). Drop
            # "fallback" — a google.com/search link dressed up with an article title reads
            # as a real corroborating source but isn't (same reason we drop it for source_url).
            if final and status in ("resolved", "kept"):
                references.append({"title": available[u], "url": final})
                seen.add(u)
    return {
        "background": str(result.get("background") or "")[:600],
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
    deep_total = 0
    for item in targets:
        try:
            queries = _extract_queries(item, ai)
            web: list[dict] = []
            seen_urls: set[str] = set()
            for q in queries:
                for r in _web_search(q):
                    u = r.get("url", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        web.append(r)
            if not web:
                # No external corroboration available → leave fields empty rather
                # than risk a fabricated background. The item keeps its summary.
                item.setdefault("background", "")
                item.setdefault("references", [])
                continue
            # Deep read: fetch the actual article for the first few results so the AI reads
            # full content, not just a snippet. A miss (paywall / block / error) keeps the
            # snippet body, so this is never worse than snippet-only enrichment.
            for r in web[:_MAX_FETCH_PER_ITEM]:
                full = _fetch_article(r.get("url", ""))
                if full:
                    r["body"] = full
                    deep_total += 1
            result = _synthesize(item, web, ai, display_name)
            if result:
                item["background"] = result["background"]
                item["references"] = result["references"]
                enriched += 1
            else:
                item.setdefault("background", "")
                item.setdefault("references", [])
        except Exception as e:
            log(f"  enrich failed for '{item.get('headline','')[:50]}': {e}")
            item.setdefault("background", "")
            item.setdefault("references", [])

    log(f"enriched {enriched}/{len(targets)} items ({deep_total} full-article deep reads)")
    return items
