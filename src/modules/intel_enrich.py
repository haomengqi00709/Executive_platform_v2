"""
intel_enrich — per-item enrichment second-pass for the intelligence sections.

For the top-N items it produces:
  - background        2-3 sentences of context a busy executive needs
  - references[]      {title, url} corroborating links

Search via Gemini grounding (NOT ddgs). ddgs is intermittently blocked on datacenter IPs — a
whole run's enrichment came back empty on Railway while a single query worked fine — so we use
the same reliable Google-Search-grounding path the main search uses: one grounded call per item
returns a background + the real cited source URLs (grounding_chunks). References are hardened
through url_utils.resolve_source_url and only real ones are kept (vertex-redirect fallbacks —
google.com/search placeholders — are dropped).

Deep read (best-effort): if a reference resolves to a real article we fetch its full text and
rewrite the background from it (richer than a snippet); a paywall / block / fetch miss simply
keeps the grounded background. Reading the article is an httpx GET (not ddgs), so it works on
Railway when the URL resolves.

Degrades gracefully: a failed grounded call returns ("", []) → the item keeps its summary with
empty enrichment fields; it is never dropped and we never fabricate a source.
"""
import html as _html
import re

import httpx

from src.ai import AIClient
from src.modules.url_utils import resolve_source_url

DEFAULT_TOP_N = 8

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


def _extract_main_text(raw_html: str) -> str:
    """Dependency-free main-text extraction: pull <p> paragraph text only (article bodies live
    in <p>; nav / ads / buttons / teasers don't). No full tag-strip fallback — a page with
    little <p> text is likely JS-rendered, a block page, or a paywall teaser, so we return the
    little there is and let the caller's length check fall back to the grounded text (no nav junk)."""
    h = re.sub(r"(?is)<(script|style|head|noscript|svg)[^>]*>.*?</\1>", " ", raw_html)
    paras = re.findall(r"(?is)<p[\s>].*?</p>", h)
    text = " ".join(re.sub(r"(?is)<[^>]+>", " ", p) for p in paras)
    return " ".join(_html.unescape(text).split())


def _fetch_article(url: str) -> str:
    """Fetch a real article URL and return its main text, or "" if the fetch fails or the
    content looks like a paywall / block stub — the caller then keeps the grounded background.
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


def _bg_prompt(item: dict) -> str:
    return (
        f"Using Google Search, write a 2-3 sentence BACKGROUND on this market-intelligence item — "
        f"the context a busy executive needs to understand and act on it (who / what / figures / "
        f"why it matters). Stay on the item's OWN subject; do not mention or look for the reader. "
        f"No preamble, no markdown.\n\nHeadline: {item.get('headline','')}\nSummary: "
        f"{item.get('summary','')}\n\nReturn ONLY the background prose."
    )


def _clean_bg(text: str) -> str:
    t = (text or "").strip()
    if t.lower().startswith("background:"):
        t = t.split(":", 1)[1].strip()
    return t[:600]


def _refs_from_sources(sources: list[dict], limit: int = 3) -> list[dict]:
    """Resolve grounding citation URLs to real article links, dropping vertex-redirect
    fallbacks (a google.com/search placeholder is not a real source). Returns [{title, url}]."""
    refs: list[dict] = []
    seen: set[str] = set()
    for s in sources:
        url = (s.get("url") or "").strip()
        if not url:
            continue
        final, status = resolve_source_url(url, headline=s.get("title", ""))
        if final and status in ("resolved", "kept") and final not in seen:
            seen.add(final)
            refs.append({"title": s.get("title") or "source", "url": final})
        if len(refs) >= limit:
            break
    return refs


def _rewrite_bg_from_article(item: dict, article_text: str, ai: AIClient) -> str:
    """Rewrite the background from a fetched full article — no search, no outside facts."""
    prompt = (
        f"Using ONLY the article below (do not add outside facts), write a 2-3 sentence background "
        f"on this item — the context a busy executive needs (who / what / figures / why it matters). "
        f"Describe the item's OWN subject; do NOT mention or look for any reader or person by name "
        f"(if the article does not name one, that is expected — never write that information about a "
        f"person is missing). No preamble, no markdown.\n\nItem: {item.get('headline','')}\n\n"
        f"Article:\n{article_text[:_MAX_ARTICLE_CHARS]}\n\nReturn ONLY the background prose."
    )
    try:
        return _clean_bg(ai.generate(prompt))
    except Exception:
        return ""


def enrich_items(
    items: list[dict],
    ai: AIClient,
    top_n: int = DEFAULT_TOP_N,
    display_name: str = "the executive",
    log=None,
) -> list[dict]:
    """Enrich the first `top_n` items in place (they arrive sorted by score, so these are the
    highest-priority). Lower items are left untouched. Always returns the full list. Reliable on
    datacenter IPs because search is via Gemini grounding, not ddgs."""
    log = log or _noop
    if not items:
        return items

    targets = items[:top_n]
    log(f"enriching top {len(targets)} of {len(items)} items (grounding)")
    enriched = 0
    deep = 0
    for item in targets:
        try:
            text, sources = ai.generate_with_search_cited(_bg_prompt(item))
            refs = _refs_from_sources(sources)
            bg = _clean_bg(text)
            # Best-effort deep read: fetch a resolved reference's full article and rewrite the
            # background from it (richer than the grounded snippet). A paywall / block / miss
            # keeps the grounded text. The fetch is httpx (not ddgs), so it works on Railway.
            for r in refs[:_MAX_FETCH_PER_ITEM]:
                full = _fetch_article(r["url"])
                if full:
                    deeper = _rewrite_bg_from_article(item, full, ai)
                    if deeper:
                        bg = deeper
                        deep += 1
                    break
            item["background"] = bg
            item["references"] = refs
            if bg:
                enriched += 1
        except Exception as e:
            log(f"  enrich failed for '{item.get('headline','')[:50]}': {e}")
            item.setdefault("background", "")
            item.setdefault("references", [])

    log(f"enriched {enriched}/{len(targets)} items ({deep} full-article deep reads)")
    return items
