"""
website_intel — extract company info from a public website URL using Gemini's
Google Search grounding (no scraping required).

Used during onboarding Step 1: user pastes their company URL, we infer the
official company name plus structured business info. The output pre-fills
Step 3's editable fields and seeds the business_profile-generation prompt so
the AI has authoritative company context before any inbox scan runs.

Returns all fields the prompt asks for, even when empty — the caller decides
how to handle missing data (business_profile renders empty sections rather
than fabricated content). Failure modes are common (sites with auth walls,
JS-only content, anti-bot); caller MUST catch exceptions and fall back to
`extract_company_name_fallback`.
"""

import json
import re
from urllib.parse import urlparse

from src.ai import AIClient


_PROMPT = """You are extracting structured company info from a website to seed an
onboarding profile. Be conservative: empty is better than wrong.

Website URL: {url}

Search for the company at this URL. Extract the following fields. **If a
field isn't clearly stated on the site, return an empty string or empty
list — do not invent.**

  company_name      — Official display name (e.g. "iModel 3D Inc." or
                      "Anthropic"). NOT the URL. Prefer the most
                      recognizable brand name if it differs from the legal
                      name.

  headquarters      — Primary location as "City, Region/State, Country"
                      (e.g. "Vancouver, BC, Canada"). Use whatever level of
                      precision the site provides. Empty if not stated.

  what_they_do      — 2-3 sentences in plain English: what the company
                      does, who they sell to. Prefer the company's own
                      wording from their About / homepage hero — quote
                      their phrasing if concise. No marketing fluff.

  business_lines    — 2-5 short bullet strings describing distinct service
                      areas or business divisions (e.g. ["3D model
                      review", "As-built studies", "Point cloud
                      automation"]). NOT product features. Empty if the
                      site presents the company as a single offering.

  products          — Named products or services (e.g. ["iModel Cloud",
                      "iModel API"]). NOT generic categories. Empty if no
                      branded products are listed.

  segments          — 3-5 short tags describing the industries / markets
                      they operate in (e.g. ["Engineering services", "Oil
                      & gas", "3D modelling"]). NOT product features.
                      Industries.

  role_emails       — Functional email addresses listed on the Contact /
                      About page (e.g. ["info@imodel3d.com",
                      "sales@imodel3d.com"]). Do NOT include named
                      individuals' emails. Empty if none are published.

Reply with valid JSON only, no markdown, no code fences:

{{
  "company_name":   "...",
  "headquarters":   "...",
  "what_they_do":   "...",
  "business_lines": ["...", "..."],
  "products":       ["...", "..."],
  "segments":       ["...", "..."],
  "role_emails":    ["...", "..."]
}}

If the site is not loadable or you can't find any info, return all fields
empty.
"""


def extract_company_info(url: str, ai: AIClient) -> dict:
    """Extract structured company info from a public URL.

    Raises on AI failure — caller should catch and use heuristic fallback.
    Returns a dict with all 7 keys; values default to "" / [] when AI
    can't find them. Backwards compat: the legacy `description` key is
    populated from `what_they_do` so older callers don't break.
    """
    if not url or not url.strip():
        raise ValueError("URL is required")
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    raw = ai.generate_with_search(_PROMPT.format(url=url))
    # generate_with_search returns plain text — may include code fences despite
    # the prompt asking otherwise (Gemini's Google Search grounding doesn't
    # honor "no markdown" as strictly as extract_json does).
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object in response: {raw[:200]}")
    parsed = json.loads(m.group(0))

    def _str(key: str) -> str:
        return (parsed.get(key) or "").strip()

    def _list(key: str, cap: int) -> list[str]:
        raw_list = parsed.get(key) or []
        if not isinstance(raw_list, list):
            return []
        return [s.strip() for s in raw_list if isinstance(s, str) and s.strip()][:cap]

    # Validate the AI-extracted company name against the URL. Gemini Search
    # Grounding is non-deterministic; on sparse sites it sometimes pattern-
    # matches to a similar-named company from training data (e.g. returned
    # "Sunshine AI Advisory" for trustedaiadvisory.ca).
    #
    # When the name is rejected, ALL OTHER FIELDS are also tainted — they
    # describe the wrong company. Returning just an empty company_name but
    # keeping `what_they_do` / `business_lines` etc would let the hallucinated
    # description through (as actually happened in production — settings.
    # company_what_they_do ended up "Sunshine AI Advisory provides ..." even
    # though company_name was rejected). So nuke the whole result and let
    # the caller's URL-heuristic fallback produce a clean empty record.
    raw_name = _str("company_name")
    if raw_name and not _name_plausibly_matches_url(raw_name, url):
        return {
            "company_name":   "",
            "headquarters":   "",
            "what_they_do":   "",
            "business_lines": [],
            "products":       [],
            "segments":       [],
            "role_emails":    [],
            "description":    "",
        }

    what_they_do = _str("what_they_do")
    return {
        "company_name":   raw_name,
        "headquarters":   _str("headquarters"),
        "what_they_do":   what_they_do,
        "business_lines": _list("business_lines", 8),
        "products":       _list("products", 8),
        "segments":       _list("segments", 5),
        "role_emails":    _list("role_emails", 8),
        # Backwards compat — older callers (existing wizard mock data, tests)
        # still read `description`. Map it to what_they_do.
        "description":    what_they_do,
    }


# Trivial words that appear in many company names and should NOT count as
# "significant evidence" of a URL↔name match.
_GENERIC_WORDS = frozenset({
    "ai", "the", "and", "for", "of", "in", "co",
    "inc", "llc", "ltd", "corp", "corporation", "company", "group", "holdings",
    "services", "solutions", "consulting", "advisory", "advisors", "partners",
    "labs", "technologies", "tech", "software", "systems", "platform",
})


def _name_plausibly_matches_url(name: str, url: str) -> bool:
    """Heuristic check: does the AI-extracted company name share at least one
    significant word with the URL host? Used to filter out hallucinations.

    A "significant" word is any 3+ char lowercase token that isn't in the
    generic-words set. The URL host is stripped of dots/TLDs and lowercased,
    then we substring-match each significant name word against it.

    Examples (host derived from URL):
      "Trusted AI Advisory Services" vs trustedaiadvisory.ca
        significant: ['trusted']         "trusted" in "trustedaiadvisoryca" → True ✅
      "Sunshine AI Advisory" vs trustedaiadvisory.ca
        significant: ['sunshine']        "sunshine" in "trustedaiadvisoryca" → False ❌
      "Anthropic, PBC" vs anthropic.com
        significant: ['anthropic']       "anthropic" in "anthropiccom" → True ✅

    If the name has NO significant words (e.g. "AI Co"), default to True —
    we can't reject something we can't evaluate.
    """
    if not name or not url:
        return True
    try:
        host = (urlparse(url).hostname or "").lower().replace(".", "")
    except Exception:
        return True
    if not host:
        return True

    name_words = re.findall(r"[a-z]+", name.lower())
    significant = [w for w in name_words if len(w) >= 3 and w not in _GENERIC_WORDS]
    if not significant:
        return True
    return any(w in host for w in significant)


def extract_company_name_fallback(url: str) -> str:
    """Best-effort name from the URL alone when AI extraction fails.

    imodel3d.com    -> iModel 3d
    abc-corp.co.uk  -> Abc Corp
    """
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    # Take the leftmost label of the domain
    label = host.split(".")[0] if host else ""
    if not label:
        return ""
    # Heuristic prettification: split on dashes, title-case each part,
    # don't touch internal digits (so "imodel3d" stays "Imodel3d" — acceptable).
    return " ".join(p.title() for p in label.split("-") if p)
