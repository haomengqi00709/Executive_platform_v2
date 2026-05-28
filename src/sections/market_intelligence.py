"""
market_intelligence section — Scheduled
Macro market signals via Gemini Google Search grounding.
Structured items: headline (point-form) + summary + source_url + 7-day dedup.
"""
import hashlib
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context
from src.modules.url_utils import resolve_source_url

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "market_intelligence"
_RESULT_ID = "market_intelligence"

_DEFAULT_INSTRUCTION = """\
# Market Intelligence — Search Instruction

*Edit this document to define exactly what market intelligence you want to receive each day.*
*The AI will use these instructions to search Google for relevant signals.*

---

## Briefing Name
Daily Market Intelligence — [Your Focus Area]

## Scope

### Geographies
- [e.g. Canada, USA, Europe, Asia-Pacific]

### Industries
- [e.g. Construction & Engineering, SaaS, Financial Services, Healthcare, Oil & Gas]

### Project / Opportunity Types
- [e.g. capital project approvals, RFPs, digital transformation initiatives, M&A activity]

### Signal Types
- New projects announced or tendered
- Funding rounds and capital investment news
- Leadership / ownership changes at key industry players
- Regulatory or policy changes affecting your sector
- Competitor moves, partnerships, and product launches
- Macroeconomic signals: supply chain, commodity prices, workforce trends

## Research Steps
1. Search for recent news (last 14 days) across the target geographies and industries above
2. Focus on signals relevant to [your product/service — e.g. AI consulting, ERP implementation, capital project advisory]
3. Prioritise signals from named companies in your client list or target account list
4. Exclude generic think-pieces with no actionable signal and press releases older than 14 days
5. Do not repeat items already covered in recent briefings

## Exclusions
- Consumer / retail news unrelated to B2B
- Generic industry opinion pieces with no specific event or signal
- [Add your own exclusions here]
"""


def _load_skill_doc() -> str:
    path = _SKILLS_DIR / "skill.md"
    return path.read_text().strip() if path.exists() else ""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / "market_intelligence.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _load_seen(data_dir: Path) -> dict:
    path = data_dir / "market_intel_seen.json"
    if not path.exists():
        return {}
    try:
        seen = json.loads(path.read_text())
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        return {k: v for k, v in seen.items() if v >= cutoff}
    except Exception:
        return {}


def _save_seen(data_dir: Path, seen: dict) -> None:
    (data_dir / "market_intel_seen.json").write_text(json.dumps(seen, indent=2))


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

    parse_prompt = f"""The following is market intelligence content retrieved via web search.
Extract all distinct market intelligence items and format as a JSON array.

Each item must have exactly these fields:
- headline: one concise sentence (point-form style)
- summary: 2-4 sentences with specific details and implications
- signal_type: one of regulatory | funding | M&A | technology | competitive | macro | other
- source: publication or platform name
- source_url: full URL of the original article (real URL from search results, or "" if not available)
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
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("headline"):
            continue
        out.append({
            "headline":      str(item.get("headline") or "")[:200],
            "summary":       str(item.get("summary") or item.get("detail") or "")[:600],
            "signal_type":   item.get("signal_type") or "other",
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
        print(f"[market_intelligence] {msg}")

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
    seen = _load_seen(data_dir)

    skill_filled = (
        skill_doc
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{user_instruction}", user_instruction)
    )
    context_block = f"Business context: {business_context}\n\n" if business_context else ""

    search_prompt = f"""You are a market intelligence analyst. Today is {date_str}.
{context_block}{skill_filled}

Search Google for current market signals. Return ONLY a JSON array — no markdown, no preamble. Example:
[
  {{
    "headline": "Alberta announces $2B infrastructure tender for highway expansion",
    "summary": "The Alberta government released a public tender for a major highway expansion project...",
    "signal_type": "regulatory",
    "source": "CBC News",
    "source_url": "https://www.cbc.ca/news/...",
    "published_date": "2026-05-20",
    "relevance": "Direct opportunity for capital project advisory services in Western Canada.",
    "priority": "high"
  }}
]"""

    _p("Searching for market intelligence signals...")
    try:
        raw = ai.generate_with_search(search_prompt)
    except Exception as e:
        _p(f"Search failed: {e}")
        return {
            "id": _RESULT_ID, "status": "error", "error": str(e),
            "items": [], "count": 0, "empty": True,
            "last_run": datetime.now(timezone.utc).isoformat(),
        }

    _p("Parsing results...")
    items = _normalise(_parse_raw(raw, ai))
    items = _resolve_urls(items, _p)

    if not items:
        _p("No items extracted")
        return {
            "id": _RESULT_ID, "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "items": [], "count": 0, "empty": True,
        }

    _p(f"{len(items)} items before dedup")
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
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(items)} items saved")
    return result
