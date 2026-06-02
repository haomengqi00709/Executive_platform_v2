"""
company_intelligence section — Scheduled
Targeted intelligence on companies the user has marked for monitoring.
Structured items with company attribution and 7-day dedup.

Companies are read from companies.json (built by src/modules/companies.py
from CRM + Projects). A company is monitored when monitor_intelligence=True
and ignore=False — there is no fallback path that scans CRM or projects
directly here.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context
from src.modules.companies import load_companies
from src.modules.url_utils import resolve_source_url
from src.modules.intel_dedup import (
    load_history, save_history,
    filter_exact_duplicates, assign_ids,
    format_history_for_validator,
)

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "company_intelligence"
_RESULT_ID = "company_intelligence"

_DEFAULT_INSTRUCTION = """\
# Company Intelligence — Search Instruction

This file controls **how the AI researches** the companies you've chosen
to monitor. It does NOT decide which companies to research — that's
controlled by toggles in the Records → Companies tab.

## What this file CAN control
- AI tone and depth (deep-dive vs. summary)
- Signal types to emphasize (executive moves, M&A, partnerships, etc.)
- Time window
- Specific topic exclusions ("skip earnings call coverage")
- Dedup hints across runs

## What this file CANNOT control (use the Records → Companies tab instead)
- Which companies get researched. By default we research only companies whose
  `derived_status` ∈ {client, prospect, partner, investor}. Vendor / internal /
  other are skipped automatically — usually they're email-domain noise (Gmail,
  Outlook, Microsoft, HubSpot, etc.) rather than relationships you actively
  cultivate. **Exception**: any company you manually added via the "Add Company"
  button is always researched regardless of status.
- To force monitoring of a vendor / internal / other auto-derived company:
  change that contact's CRM status to "prospect" (Records → CRM), or
  delete-then-re-add the company manually
- To skip a specific company you don't want researched:
  toggle `ignore = True` on it in Records → Companies
- To re-order monitoring priority: set `priority = high` on it

---

Monitor specific companies I work with for recent signals.
Focus on: executive announcements on LinkedIn or X, new contracts or partnerships,
leadership changes, product launches, and strategic decisions.

## Time Window
Last 30 days.

## Priority Focus
- LinkedIn posts or X threads from C-suite / VP-level executives
- Press releases and official company announcements
- News coverage of the company (not just industry background)

## Exclusions
- Generic industry articles that mention the company in passing
- Old news (>30 days)
"""

_COMPANY_CAP = 25  # AI search cost ceiling — must not silently grow
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_STATUS_RANK   = {
    "client":   0, "prospect": 1, "partner": 2, "investor": 3,
    "vendor":   4, "internal": 5, "other":    6,
}

# Only research companies the user actively cultivates. vendor / internal /
# other are typically email-domain noise (free-mail providers auto-becoming
# "Gmail" / "Outlook" / "Qq" companies, SaaS notification senders becoming
# "HubSpot" / "Brevo" / "Microsoft", etc.) — never the executive's strategic
# focus. If a user has a genuine vendor they want monitored, they change
# that contact's CRM status to "prospect" / "partner" (already supported).
_MONITORED_STATUSES = frozenset({"client", "prospect", "partner", "investor"})


def _load_skill_doc() -> str:
    path = _SKILLS_DIR / "skill.md"
    return path.read_text().strip() if path.exists() else ""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / "company_intelligence.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _build_company_list(data_dir: Path) -> list[str]:
    """Pull the list of company names to research from companies.json.

    A company is included when:
      - monitor_intelligence=True AND ignore=False, AND
      - EITHER derived_status ∈ _MONITORED_STATUSES (client/prospect/partner/investor)
        OR  manual=True (user explicitly added via UI / migrated from watchlist)

    The status filter is the load-bearing line for noise reduction: it drops
    auto-generated junk like "Gmail" / "Outlook" / "HubSpot" / "Microsoft"
    that gets created when free-email or SaaS notification senders enter CRM.
    The manual-bypass clause protects user-curated watchlist entries
    (e.g. Arup, WSP, GHD) which typically have status="other" because they
    have no CRM contacts yet — but the user explicitly wants them tracked.

    For a vendor user genuinely cares about, change that contact's CRM
    status to "prospect" / "partner" via Records → CRM.

    Order: per-company priority (high < medium < low), then derived_status
    (client first, investor last), then name. Capped at _COMPANY_CAP.
    """
    db = load_companies(data_dir)
    ranked: list[tuple[int, int, str]] = []
    for c in (db.get("companies") or {}).values():
        if not c.get("monitor_intelligence") or c.get("ignore"):
            continue
        status = c.get("derived_status") or "other"
        if status not in _MONITORED_STATUSES and not c.get("manual"):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        prio     = _PRIORITY_RANK.get(c.get("priority") or "medium", 1)
        status_r = _STATUS_RANK.get(status, 6)
        ranked.append((prio, status_r, name))
    ranked.sort(key=lambda x: (x[0], x[1], x[2].lower()))
    return [name for _, _, name in ranked[:_COMPANY_CAP]]


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _parse_raw(raw: str, ai: AIClient) -> list[dict]:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(clean)
        if isinstance(result, list):
            return result
    except Exception:
        pass

    parse_prompt = f"""The following is company intelligence content retrieved via web search.
Extract all distinct company intelligence items and format as a JSON array.

Each item must have exactly these fields:
- company: exact company name
- headline: one-sentence strategic insight (not a news headline)
- summary: 2-4 sentences with specific details and implications
- signal_type: one of executive_statement | announcement | leadership | funding | M&A | other
- person: executive name if applicable, or empty string
- source: LinkedIn | X | News | Press Release | other
- source_url: full URL of original post/article, or empty string
- published_date: YYYY-MM-DD or empty string
- relevance: one sentence on why this matters to the executive
- priority: high | medium | low

Content:
{raw[:4000]}"""
    try:
        result = json.loads(ai.extract_json(parse_prompt))
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _resolve_urls(items: list[dict], log) -> list[dict]:
    """Replace each item's source_url with the resolved real URL.

    Gemini's grounding output is short-lived and often polluted; resolving here
    at scan time captures the permanent destination before the redirect dies.
    """
    counts = {"resolved": 0, "kept": 0, "fallback": 0, "empty": 0}
    for item in items:
        final, status = resolve_source_url(
            item.get("source_url", ""),
            headline=item.get("headline", ""),
            source=item.get("source", ""),
        )
        item["source_url"] = final
        counts[status] = counts.get(status, 0) + 1
    log(f"URLs: {counts['resolved']} resolved · {counts['kept']} kept · "
        f"{counts['fallback']} fallback · {counts['empty']} empty")
    return items


def _normalise(items: list[dict]) -> list[dict]:
    valid_signal_types = {"executive_statement", "announcement", "leadership", "funding", "M&A", "other"}
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("headline") or not item.get("company"):
            continue
        out.append({
            "company":       str(item.get("company") or "")[:100],
            "headline":      str(item.get("headline") or "")[:200],
            "summary":       str(item.get("summary") or "")[:600],
            "signal_type":   item.get("signal_type") if item.get("signal_type") in valid_signal_types else "other",
            "person":        str(item.get("person") or "")[:100],
            "source":        str(item.get("source") or "")[:100],
            "source_url":    str(item.get("source_url") or "")[:500],
            "published_date": str(item.get("published_date") or "")[:10],
            "relevance":     str(item.get("relevance") or "")[:200],
            "priority":      item.get("priority") if item.get("priority") in ("high", "medium", "low") else "medium",
        })
    return out


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict,
    progress=None,
    force_refresh: bool = False,
) -> dict:
    def _p(msg: str):
        if progress:
            progress(msg)
        print(f"[company_intelligence] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    display_name = settings.get("display_name") or "the executive"
    business_context = load_profile_context(data_dir)
    date_str = datetime.now().strftime("%A, %B %d, %Y")

    skill_doc = _load_skill_doc()
    if not skill_doc:
        _p("No skill.md found")
        return {"id": _RESULT_ID, "status": "not_run", "items": [], "count": 0, "empty": True}

    user_instruction = _load_user_instruction(data_dir)

    companies = _build_company_list(data_dir)
    if not companies:
        _p("No companies flagged for monitoring in companies.json")
        return {
            "id": _RESULT_ID, "status": "not_run",
            "items": [], "count": 0, "empty": True,
            "empty_reason": "no_companies",
        }

    _p(f"Tracking {len(companies)} companies: {', '.join(companies[:8])}{'...' if len(companies) > 8 else ''}")

    history = load_history(data_dir, "company_intel")

    skill_filled = (
        skill_doc
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{user_instruction}", user_instruction)
    )
    context_block = f"Business context: {business_context}\n\n" if business_context else ""

    all_items: list[dict] = []
    batches = list(_chunks(companies, 5))

    for i, batch in enumerate(batches, 1):
        company_list = "\n".join(f"- {c}" for c in batch)
        _p(f"Searching batch {i}/{len(batches)}: {', '.join(batch)}")

        search_prompt = f"""You are a company intelligence analyst. Today is {date_str}.
{context_block}{skill_filled}

Search Google for recent intelligence on ONLY these specific companies:
{company_list}

Return ONLY a JSON array — no markdown, no preamble. Include only companies where you found real intelligence. Example:
[
  {{
    "company": "Acme Corp",
    "headline": "Acme CEO signals pivot to AI-first infrastructure — legacy product lines being wound down",
    "summary": "In a LinkedIn post on May 20, Acme CEO Jane Smith outlined...",
    "signal_type": "executive_statement",
    "person": "Jane Smith",
    "source": "LinkedIn",
    "source_url": "https://www.linkedin.com/posts/...",
    "published_date": "2026-05-20",
    "relevance": "Direct opportunity to position AI consulting before their Q3 transformation budget is set.",
    "priority": "high"
  }}
]"""

        try:
            raw = ai.generate_with_search(search_prompt)
            batch_items = _parse_raw(raw, ai)
            all_items.extend(batch_items)
            _p(f"  → {len(batch_items)} items from batch {i} (general)")
        except Exception as e:
            _p(f"  → Batch {i} general search failed: {e}")

        # Second pass: LinkedIn + X targeted search
        social_prompt = f"""You are a company intelligence analyst. Today is {date_str}.
{context_block}
Search LinkedIn (site:linkedin.com) and X/Twitter (site:x.com OR site:twitter.com) for executive posts and company updates from the last 30 days for ONLY these companies:
{company_list}

Focus on:
- LinkedIn posts or articles by C-suite / VP-level executives at these companies
- X/Twitter threads from official company accounts or named executives
- Statements about strategy, products, partnerships, culture changes, or market views

Return ONLY a JSON array — no markdown, no preamble. Skip companies with no social posts found. Each item:
[
  {{
    "company": "exact company name",
    "headline": "one-sentence strategic insight from the post",
    "summary": "2-3 sentences: who posted, what they said, what it signals",
    "signal_type": "executive_statement",
    "person": "executive name",
    "source": "LinkedIn",
    "source_url": "full URL of the post",
    "published_date": "YYYY-MM-DD",
    "relevance": "why this matters to {display_name}",
    "priority": "high | medium | low"
  }}
]"""

        try:
            raw_social = ai.generate_with_search(social_prompt)
            social_items = _parse_raw(raw_social, ai)
            all_items.extend(social_items)
            _p(f"  → {len(social_items)} items from batch {i} (social)")
        except Exception as e:
            _p(f"  → Batch {i} social search failed: {e}")

    if not all_items:
        _p("No items extracted from any batch")
        return {
            "id": _RESULT_ID, "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "items": [], "count": 0, "empty": True,
        }

    items = _normalise(all_items)
    _p(f"{len(items)} valid items before dedup")
    items = _resolve_urls(items, _p)

    # Layer 2 context: snapshot the PRIOR history (from previous runs)
    # BEFORE we add today's items. If we formatted after the md5 step,
    # the validator would see today's own candidates listed as
    # "previously surfaced" and reject all of them as duplicates.
    history_context = format_history_for_validator(history)

    # Layer 1: md5-exact dedup (cheap, lossless) — drops items whose
    # headline exactly matches one we've already surfaced in the last 7 days.
    # Mutates `history` in place to record today's new items.
    items, history = filter_exact_duplicates(items, history)
    _p(f"{len(items)} new items after md5 dedup")

    items = assign_ids(items)

    # Layer 2: AI semantic dedup at validator stage — sees previously-
    # surfaced headlines (from prior runs only) and drops items describing
    # the same news event even if wording / source differs. Empty
    # history_context falls back to the validator's pre-fix behavior.
    items = validate_output(
        items, ai,
        section_id=_RESULT_ID,
        user_instruction=user_instruction,
        display_name=display_name,
        date_str=date_str,
        extra_context=history_context,
    )

    save_history(data_dir, "company_intel", history)

    result = {
        "id": _RESULT_ID,
        "status": "fresh",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "count": len(items),
        "empty": len(items) == 0,
        "companies_tracked": len(companies),
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(items)} items across {len(companies)} companies")
    return result
