"""
market_intelligence section — Scheduled
Macro market signals via Gemini Google Search grounding.
Structured items: headline (point-form) + summary + source_url + 7-day dedup.
"""
import json
from datetime import datetime, timezone, timedelta, date
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
from src.modules.intel_score import score_items, DEFAULT_THRESHOLD
from src.modules.feed_rewrite import rewrite_feed_items
from src.modules.intel_enrich import enrich_items
from src.modules.feeds_config import load_feeds
from src.modules.feeds_fetch import fetch_feed_items

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "market_intelligence"
_RESULT_ID = "market_intelligence"
_FEED_LOOKBACK_DAYS = 30  # recency window for feed items — wider than grounding's
                          # 14d because niche B2B verticals publish less often;
                          # relevance scoring gates them regardless of age
_SEARCH_TIMEOUT_SECS = 180  # one rich instruction-driven grounding search legitimately
                            # runs longer than the 60s default; widen here instead of
                            # chopping the search into generic topic batches to fit 60s

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
1. Search for recent news (last 30 days) across the target geographies and industries above
2. Focus on signals relevant to [your product/service — e.g. AI consulting, ERP implementation, capital project advisory]
3. Prioritise signals from named companies in your client list or target account list
4. Exclude generic think-pieces with no actionable signal and press releases older than 30 days
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


def _build_search_prompt(skill_filled: str, context_block: str, angle: str | None = None) -> str:
    """Minimal instruction-driven search prompt = business context + the lean skill.md
    (role + how-to-search + the user's verbatim instruction + output spec; skill.md is the
    source of truth). Kept deliberately lean: an N=5 A/B vs the heavier scaffolded prompt
    showed this ties on client coverage + junk and wins on count-stability + schema
    cleanliness. Ranking / dedup / validation happen AFTER the search, not in this prompt.

    When `angle` is given (one fan-out leg — a named client or a focus area), the search is
    narrowed to it while still honouring the instruction's window, exclusions, and schema."""
    base = f"{context_block}{skill_filled}"
    if angle:
        base += (f"\n\n## This search's focus\n"
                 f"For THIS particular search only, focus specifically on: {angle}\n"
                 f"Still honour the instruction's time window, exclusions, and output schema above.")
    return base


_MAX_ANGLES = 6   # cap fan-out so a long client list can't explode the search cost
_MAX_ITEMS = 12   # final brief size — fan-out floods, so rank by relevance and keep the top N
_RECENCY_DEFAULT_DAYS = 30  # default hard recency cap (days); per-user override lives in
                           # settings["market_intel_recency_days"]. The model/validator don't
                           # reliably honour the window, so we hard-drop dated-older items.


def _plan_search_angles(ai: AIClient, business_context: str, user_instruction: str,
                        display_name: str) -> list[str]:
    """Derive up to _MAX_ANGLES targeted search angles from the user's OWN data so the
    fan-out reliably covers their named companies and focus areas, instead of leaning on a
    single stochastic grounding search. General: angles are read from the business context +
    instruction, never hardcoded. Returns [] on failure → caller falls back to one search."""
    if not (business_context.strip() or user_instruction.strip()):
        return []
    prompt = f"""You are planning a market-intelligence search for {display_name}.

Business context:
{business_context}

Their market-intelligence instruction:
{user_instruction}

Produce a JSON array of AT MOST {_MAX_ANGLES} short search angles that together cover this
person's daily market intelligence comprehensively:
- one angle per specific company they care about (named clients / partners / competitors in
  the business context), and
- one angle per key focus area / priority in their instruction.
Each angle is a short phrase naming the target plus the relevant focus (e.g.
"<Company> brownfield upgrades and digital-twin activity", or
"as-built laser scanning and asset integrity in oil & gas").
Output ONLY a JSON array of strings, at most {_MAX_ANGLES} items."""
    try:
        angles = json.loads(ai.extract_json(prompt))
        if isinstance(angles, list):
            return [str(a).strip() for a in angles if str(a).strip()][:_MAX_ANGLES]
    except Exception:
        pass
    return []


def _dedup_raw(items: list[dict]) -> list[dict]:
    """Within-run dedup across fan-out legs (the same event surfaced by several angles),
    by source_url then headline prefix. Cheap; runs before the score/enrich/validate passes."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        url = (it.get("source_url") or "").strip().lower()
        key = url or str(it.get("headline", ""))[:50].lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _filter_recent(items: list[dict], cutoff_days: int) -> tuple[list[dict], int]:
    """Hard recency cap: drop items whose published_date is present AND older than
    cutoff_days. Items with an empty/unparseable date are kept (don't over-filter on a
    missing field). Returns (kept, n_dropped)."""
    cutoff = (date.today() - timedelta(days=cutoff_days)).isoformat()
    kept: list[dict] = []
    dropped = 0
    for it in items:
        d = (it.get("published_date") or "").strip()
        if d and d < cutoff:
            dropped += 1
            continue
        kept.append(it)
    return kept, dropped


def _recency_days(settings: dict) -> int:
    """Per-user recency cap in days (settings.market_intel_recency_days), clamped to a sane
    range; falls back to _RECENCY_DEFAULT_DAYS when unset or invalid."""
    try:
        return max(1, min(int(settings.get("market_intel_recency_days")), 365))
    except (TypeError, ValueError):
        return _RECENCY_DEFAULT_DAYS


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
            "origin":        item.get("origin") or "grounding",
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

    # Structured fan-out: one grounding search per angle (a named client or a focus area),
    # then merge + dedup. A single grounding call is one stochastic slice — even on a strict
    # window it reliably covers neither every client nor the full focus list (proven: two
    # runs of the same prompt barely overlap). Angles are derived from the user's OWN data
    # (business context + instruction) by a cheap planner call, so this stays general — no
    # hardcoded companies/topics. The wider, noisier net is cleaned by validate downstream.
    angles = _plan_search_angles(ai, business_context, user_instruction, display_name)
    if angles:
        _p(f"planned {len(angles)} search angles: {angles}")
    else:
        _p("no angles planned — falling back to one instruction-driven search")
        angles = [None]  # sentinel: a single general instruction-driven search

    all_raw_items: list[dict] = []
    ok_batches = 0
    for idx, angle in enumerate(angles, 1):
        prompt = _build_search_prompt(skill_filled, context_block, angle=angle)
        try:
            raw = ai.generate_with_search(prompt, timeout_secs=_SEARCH_TIMEOUT_SECS)
            items = _parse_raw(raw, ai)
            all_raw_items.extend(items)
            ok_batches += 1 if items else 0
            _p(f"  angle {idx}/{len(angles)} [{angle or 'general'}]: {len(items)} items")
        except Exception as e:
            _p(f"  angle {idx} [{angle or 'general'}] failed: {e}")

    before = len(all_raw_items)
    all_raw_items = _dedup_raw(all_raw_items)
    if len(all_raw_items) < before:
        _p(f"fan-out dedup: {before} → {len(all_raw_items)} unique")

    # Merge configured feed sources (RSS / Google News / HN / Reddit), if the
    # user has opted in. Feed items enter the SAME schema and pipeline; the
    # scoring gate below filters them to this reader's relevance. Per-source
    # isolation lives inside fetch_feed_items — a bad feed can't sink the run.
    feed_items: list[dict] = []
    try:
        feeds_cfg = load_feeds(data_dir)
        since = datetime.now(timezone.utc) - timedelta(days=_FEED_LOOKBACK_DAYS)
        feed_items = fetch_feed_items(feeds_cfg, since, log=_p)
        if feed_items:
            all_raw_items.extend(feed_items)
            _p(f"feeds: +{len(feed_items)} items merged")
    except Exception as e:
        _p(f"feeds: fetch failed: {e}")

    # Hard error only if grounding produced nothing AND no feed items either —
    # partial results are fine (mirrors company_intelligence).
    if ok_batches == 0 and not feed_items:
        _p("All topic searches failed and no feed items")
        return {
            "id": _RESULT_ID, "status": "error",
            "error": "all market-intelligence topic searches failed (timeout/grounding)",
            "items": [], "count": 0, "empty": True,
            "last_run": datetime.now(timezone.utc).isoformat(),
        }

    _p("Parsing results...")
    items = _normalise(all_raw_items)

    # Code-level recency cap (user-configurable: settings.market_intel_recency_days; default
    # _RECENCY_DEFAULT_DAYS). The model + validator don't reliably honour the window — they
    # backfill older items to fill the brief — so hard-drop anything dated older than the cap.
    cutoff_days = _recency_days(settings)
    items, n_old = _filter_recent(items, cutoff_days)
    if n_old:
        _p(f"recency filter: dropped {n_old} item(s) older than {cutoff_days}d")

    # Fan-out (and any configured feeds) cast a WIDE net — far more candidates than a brief
    # should hold. When that happens, score every candidate for relevance to THIS reader
    # (their profile + instruction), drop the off-target ones (< threshold; never pad), and
    # keep the top _MAX_ITEMS. A small single-search fallback stays on-instruction and skips
    # this. score_items sorts by ai_score desc, so the slice keeps the best.
    if feed_items or len(items) > _MAX_ITEMS:
        items = score_items(items, ai, reader_context=business_context,
                            instruction=user_instruction, display_name=display_name)
        above = [it for it in items if it.get("ai_score", 0.0) >= DEFAULT_THRESHOLD]
        items = above[:_MAX_ITEMS]
        _p(f"scored → {len(above)} above {DEFAULT_THRESHOLD}, kept top {len(items)}")
        if feed_items:
            # Reshape raw feed items into the brief's strategic-insight format so the
            # validator treats them like grounding items (grounding items pass through).
            items = rewrite_feed_items(items, ai, display_name=display_name,
                                       reader_context=business_context, log=_p)

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

    # Enrichment second-pass: for the top-N items, add web-grounded background +
    # REAL reference URLs via ddgs.
    # Runs after dedup (don't enrich items we're about to drop) and before the
    # validator. Degrades to empty fields if ddgs is unavailable — never fatal.
    items = enrich_items(items, ai, display_name=display_name, log=_p)

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
