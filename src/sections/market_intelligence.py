"""
market_intelligence section — Scheduled
Macro market signals via Gemini Google Search grounding.
Structured items: headline (point-form) + summary + source_url + 7-day dedup.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context
from src.modules.url_utils import resolve_source_url
from src.modules.intel_dedup import (
    load_history, save_history,
    filter_exact_duplicates, assign_ids,
    format_history_for_validator,
)

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


def _parse_raw(raw: str, ai: AIClient) -> list[dict]:
    clean = raw.strip()
    if not clean:
        return []  # empty search result = "no news" — don't fire an AI repair call on nothing
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
    history = load_history(data_dir, "market_intel")

    skill_filled = (
        skill_doc
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{user_instruction}", user_instruction)
    )
    context_block = f"Business context: {business_context}\n\n" if business_context else ""

    # Split the broad market search into focused topic batches. One big
    # open-ended grounding search blows the 60s Gemini timeout (the 2026-06
    # regression after the shared timeout was tightened to prevent hangs
    # elsewhere); company_intelligence never hit this because it searches in
    # small per-company batches. Mirror that here: each topic is a narrower
    # search that returns within 60s, and a per-topic try/except means one slow
    # topic can't wipe out the whole section.
    topics = [
        ("regulatory & macro",
         "regulatory or policy changes affecting the industry, plus macroeconomic "
         "signals (supply chain, commodity prices, workforce trends, trade policy)"),
        ("funding & M&A",
         "funding rounds, M&A activity, and capital movement in relevant sectors"),
        ("technology & competitive",
         "technology / AI shifts with competitive implications, competitor moves, "
         "new market entrants, pricing changes, and strategic pivots"),
    ]

    all_raw_items: list[dict] = []
    ok_batches = 0
    for idx, (topic_label, topic_focus) in enumerate(topics, 1):
        _p(f"Searching topic {idx}/{len(topics)}: {topic_label}")
        search_prompt = f"""You are a market intelligence analyst. Today is {date_str}.
{context_block}{skill_filled}

Search Google (last 14 days) for current market signals, focused ONLY on: {topic_focus}.
Return the 3-5 most relevant items as a JSON array — no markdown, no preamble. Example:
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
        try:
            raw = ai.generate_with_search(search_prompt)
            batch_items = _parse_raw(raw, ai)
            all_raw_items.extend(batch_items)
            ok_batches += 1
            _p(f"  → {len(batch_items)} items from '{topic_label}'")
        except Exception as e:
            _p(f"  → topic '{topic_label}' failed: {e}")

    # Hard error only if EVERY topic failed — partial results are fine (mirrors
    # company_intelligence, which keeps whatever batches succeeded).
    if ok_batches == 0:
        _p("All topic searches failed")
        return {
            "id": _RESULT_ID, "status": "error",
            "error": "all market-intelligence topic searches failed (timeout/grounding)",
            "items": [], "count": 0, "empty": True,
            "last_run": datetime.now(timezone.utc).isoformat(),
        }

    _p("Parsing results...")
    items = _normalise(all_raw_items)
    items = _resolve_urls(items, _p)

    if not items:
        _p("No items extracted")
        return {
            "id": _RESULT_ID, "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "items": [], "count": 0, "empty": True,
        }

    _p(f"{len(items)} items before dedup")

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

    save_history(data_dir, "market_intel", history)

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
