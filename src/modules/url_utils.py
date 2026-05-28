"""
URL sanitization and resolution for Gemini grounding redirect URLs.

Gemini's google_search grounding mode hands back vertex AI redirect URLs that
the section runners stored verbatim. Two problems:

1. Gemini's text output frequently pollutes source_url with trailing
   "(Source, Date)" fragments, multi-URL ';' joins, or embedded whitespace.
2. The vertex redirect token has a finite TTL — once expired the link 404s.

This module sanitizes the raw string into one valid URL, follows the redirect
at scan time to capture the permanent destination, and falls back to a Google
search query when the redirect is already dead.
"""
import re
import urllib.parse
from typing import Tuple

import httpx

_URL_RE = re.compile(r"https?://[A-Za-z0-9._\-/?#&=%:+~,]+")
_VERTEX_REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"

_TIMEOUT = 8.0
_UA = "Mozilla/5.0 (compatible; CEO-platform-link-resolver/1.0)"


def sanitize_url(raw: str) -> str:
    """Extract the first valid URL from a possibly-polluted source_url string.

    Strips trailing parenthesised metadata, '; '-joined extra URLs, and any
    embedded whitespace. Returns "" when nothing usable is found.
    """
    if not raw:
        return ""
    match = _URL_RE.search(raw.strip())
    if not match:
        return ""
    url = match.group(0)
    # Trailing punctuation that the greedy match may have swept in
    return url.rstrip(".,;:)\"'>")


def _try_request(client: httpx.Client, method: str, url: str) -> "httpx.Response | None":
    try:
        return client.request(method, url, timeout=_TIMEOUT)
    except Exception:
        return None


def resolve_redirect(url: str) -> Tuple[str, str]:
    """Follow redirects and classify the outcome.

    HEAD first (cheap); a 403/405/501 response triggers a GET retry since some
    publishers reject HEAD. Returns (final_url, outcome):
      - "ok":      2xx — final_url is the resolved permanent URL
      - "dead":    404/410 — article is genuinely gone, original URL is useless
      - "blocked": 403/anti-bot/5xx/network error/timeout — server refused us
                   or had a transient problem; original URL may still work in
                   a real browser
    """
    if not url:
        return ("", "blocked")
    with httpx.Client(
        follow_redirects=True,
        timeout=_TIMEOUT,
        headers={"User-Agent": _UA},
    ) as client:
        resp = _try_request(client, "HEAD", url)
        if resp is None:
            return ("", "blocked")
        if resp.status_code in (403, 405, 501):
            resp = _try_request(client, "GET", url)
            if resp is None:
                return ("", "blocked")
        if resp.status_code in (404, 410):
            return ("", "dead")
        if resp.status_code >= 400:
            return ("", "blocked")
        return (str(resp.url), "ok")


def google_search_fallback(headline: str, source: str = "") -> str:
    """Build a Google search URL so the user can still find the article."""
    q = (headline or "").strip()
    if source:
        q = f"{q} {source}".strip()
    if not q:
        return ""
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"


def resolve_source_url(
    raw_url: str,
    headline: str = "",
    source: str = "",
) -> Tuple[str, str]:
    """End-to-end resolver used by section runners.

    Returns (final_url, status) where status is:
      - "resolved": real destination URL captured via redirect follow
      - "kept":     resolve failed but URL was already a permanent direct link
                    (publisher likely blocked our HEAD bot — link should still work
                    in a real browser)
      - "fallback": vertex grounding redirect that we could not resolve — the
                    redirect token alone is useless, so a Google search URL is
                    returned instead
      - "empty":    no URL given and no headline to build a fallback from
    """
    clean = sanitize_url(raw_url)
    if not clean:
        fb = google_search_fallback(headline, source)
        return (fb, "fallback") if fb else ("", "empty")

    final, outcome = resolve_redirect(clean)
    if outcome == "ok":
        return (final, "resolved")

    # outcome is "dead" or "blocked":
    #   - dead: article 404'd — original is useless, fall back to Google search
    #   - blocked: server refused our bot or timed out — keep the original since
    #     a real browser may still load it. Vertex redirect tokens are an exception:
    #     they're useless without successful resolution.
    is_vertex = clean.startswith(_VERTEX_REDIRECT_PREFIX)
    if outcome == "dead" or is_vertex:
        fb = google_search_fallback(headline, source)
        return (fb, "fallback") if fb else (clean, "fallback")
    return (clean, "kept")
