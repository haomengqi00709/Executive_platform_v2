"""
company_intelligence section — Scheduled
Targeted intelligence on CRM companies, project participants, and custom watchlist.
Structured items with company attribution and 7-day dedup.
"""
import hashlib
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "company_intelligence"
_RESULT_ID = "company_intelligence"

_DEFAULT_INSTRUCTION = """\
# Company Intelligence — Search Instruction

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

_AUTO_CRM_STATUSES = {"client", "prospect", "partner", "investor"}
_STATUS_PRIORITY   = {"client": 0, "prospect": 1, "partner": 2, "investor": 1}
_WATCHLIST_PRIORITY = 1  # between prospect and partner — user-defined list is high priority
_ACTIVE_PROJECT_STATUSES = {"ongoing", "needs_attention", "paused", "early_stage"}


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


def _load_seen(data_dir: Path) -> dict:
    path = data_dir / "company_intel_seen.json"
    if not path.exists():
        return {}
    try:
        seen = json.loads(path.read_text())
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        return {k: v for k, v in seen.items() if v >= cutoff}
    except Exception:
        return {}


def _save_seen(data_dir: Path, seen: dict) -> None:
    (data_dir / "company_intel_seen.json").write_text(json.dumps(seen, indent=2))


def _build_company_list(data_dir: Path, crm_data: dict, projects_data: dict) -> list[str]:
    seen_lower: set[str] = set()
    companies: list[tuple[int, str]] = []  # (priority_rank, name)

    # Custom watchlist — loaded first so CRM dedup preserves watchlist companies
    watchlist_path = data_dir / "market_watchlist.json"
    if watchlist_path.exists():
        try:
            for name in json.loads(watchlist_path.read_text()):
                name = str(name).strip()
                if name and name.lower() not in seen_lower:
                    seen_lower.add(name.lower())
                    companies.append((_WATCHLIST_PRIORITY, name))
        except Exception:
            pass

    # CRM contacts — only client / prospect / partner, not low priority
    for contact in crm_data.get("contacts", {}).values():
        if contact.get("ignore") or contact.get("archived") or contact.get("priority") == "ignore":
            continue
        if contact.get("priority") == "low":
            continue
        status = contact.get("status", "other")
        company = (contact.get("company") or "").strip()
        if not company or status not in _AUTO_CRM_STATUSES:
            continue
        key = company.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            companies.append((_STATUS_PRIORITY[status], company))

    # Projects — cross-ref participants with CRM (client/prospect/partner, not low priority)
    contacts = crm_data.get("contacts", {})
    for proj in projects_data.get("projects", {}).values():
        if proj.get("ignore") or proj.get("archived") or proj.get("status") not in _ACTIVE_PROJECT_STATUSES:
            continue
        for email in proj.get("participants", []):
            contact = contacts.get(email.lower(), {})
            if contact.get("status", "other") not in _AUTO_CRM_STATUSES:
                continue
            if contact.get("priority") in ("low", "ignore"):
                continue
            company = (contact.get("company") or "").strip()
            if not company:
                continue
            key = company.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                rank = _STATUS_PRIORITY.get(contact.get("status"), 2)
                companies.append((rank, company))

    companies.sort(key=lambda x: x[0])
    return [c for _, c in companies[:25]]


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _dedup(items: list[dict], seen: dict) -> tuple[list[dict], dict]:
    today_str = date.today().isoformat()
    new_items = []
    for item in items:
        key = hashlib.md5(item.get("headline", "").lower().strip().encode()).hexdigest()[:12]
        if key not in seen:
            new_items.append(item)
            seen[key] = today_str
    return new_items, seen


def _assign_ids(items: list[dict]) -> list[dict]:
    return [{**item, "id": hashlib.sha1(item.get("headline", "").encode()).hexdigest()[:16]} for item in items]


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

    # Load CRM and projects
    crm_data = {}
    try:
        crm_path = data_dir / "crm.json"
        if crm_path.exists():
            crm_data = json.loads(crm_path.read_text())
    except Exception:
        pass

    projects_data = {}
    try:
        proj_path = data_dir / "projects.json"
        if proj_path.exists():
            projects_data = json.loads(proj_path.read_text())
    except Exception:
        pass

    companies = _build_company_list(data_dir, crm_data, projects_data)
    if not companies:
        _p("No companies to track — CRM empty and no watchlist")
        return {
            "id": _RESULT_ID, "status": "not_run",
            "items": [], "count": 0, "empty": True,
            "empty_reason": "no_companies",
        }

    _p(f"Tracking {len(companies)} companies: {', '.join(companies[:8])}{'...' if len(companies) > 8 else ''}")

    seen = _load_seen(data_dir)

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

    items, seen = _dedup(items, seen)
    _p(f"{len(items)} new items after 7-day dedup")

    items = _assign_ids(items)

    items = validate_output(
        items, ai,
        section_id=_RESULT_ID,
        user_instruction=user_instruction,
        display_name=display_name,
        date_str=date_str,
    )

    _save_seen(data_dir, seen)

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
