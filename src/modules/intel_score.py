"""
intel_score — 0-10 relevance scoring + gate for the intelligence sections.

Adapted from Horizon's CONTENT_ANALYSIS rubric, rewritten for the CEO-advisor
context. The AI assigns a 0-10 score + one-line reason per item, judged against
THIS reader's own business context (a water-pump client scores for water-pump
relevance; an AI client for AI relevance). Code — not the AI — does the
threshold filter, the sort, and the priority bucketing.

Why this is load-bearing: it's the gate that makes broad feed sources usable.
Grounding items arrive already relevance-targeted, but RSS/HN/Reddit items are a
wide net — scoring drops the off-target majority before the expensive enrichment
pass ever runs.

AI boundary (per CLAUDE.md): the AI only judges relevance. The numeric compare,
the sort, and the high/medium/low bucket are computed in Python. We never write
`ai_response.get("score") or default` — a real 0 must not be swallowed.
"""
import json

from src.ai import AIClient

# Items scoring below this are dropped by the caller's gate. 6.0 keeps
# "worth knowing" and above; tune per section if needed.
DEFAULT_THRESHOLD = 6.0

# Score → priority bucket. Survivors of a 6.0 gate are medium or high.
_HIGH_BAND = 8.0
_MEDIUM_BAND = 6.0

_CHUNK = 12  # items per scoring call — keeps the prompt small and the parse reliable

_SCORING_SYSTEM = """You are a senior intelligence analyst scoring how relevant each item is to ONE specific executive's business. Score 0-10 on relevance + importance TO THIS READER — not on generic newsworthiness.

- 10    Act now — directly affects this business: a client/competitor move, a regulation with a deadline, a live tender/opportunity, a direct threat.
- 8-9   High value — a strong strategic signal this executive should read this week.
- 6-7   Worth knowing — relevant context for this business, but not urgent.
- 4-5   Tangential — same broad industry, but no specific implication for this business.
- 2-3   Off-target — adjacent or general news with little bearing on this reader.
- 0-1   Noise — irrelevant, promotional, or off-topic for this business.

A technically impressive or popular item with no bearing on THIS reader's business or geography scores LOW. Judge against the specific business and region described below."""

# Used by company_intelligence, where the companies are ALREADY user-curated — so
# we score how MATERIAL each development is for the company it concerns, NOT whether
# the company is relevant to the reader (that decision was already made upstream).
_MATERIALITY_SYSTEM = """You are a senior intelligence analyst scoring how MATERIAL each development is for the specific company it concerns. These companies were ALREADY chosen by the executive for monitoring, so do NOT score "relevance to the executive's business" — score how significant the development itself is for that company.

- 10    Major strategic move: M&A, CEO/C-suite change, major product launch, large contract/partnership, restructuring, or legal/regulatory action with real impact.
- 8-9   Significant: a strategy-signalling executive statement, meaningful partnership/product, funding round, or market expansion.
- 6-7   Worth knowing: an incremental announcement, mid-level update, or routine partnership.
- 4-5   Minor: a small update, generic blog post, or conference appearance.
- 2-3   Trivial: a passing mention, routine analyst note, or minor PR.
- 0-1   Noise: a stock-price blip with no underlying news, promotional fluff, or off-topic content.

Judge the development's significance FOR THAT COMPANY. A routine stock movement or generic mention scores LOW even for an important company."""


def _format_items(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        signal = item.get("signal_type", "other")
        headline = (item.get("headline") or "(no headline)")[:160]
        source = item.get("source") or "—"
        lines.append(f"[{i}] [{signal}] {headline} — {source}")
        summary = (item.get("summary") or "")[:200]
        if summary:
            lines.append(f"    {summary}")
    return "\n".join(lines)


def _coerce_score(raw) -> float | None:
    """Parse a score to a float in [0, 10]. None when unparseable (so the caller
    can decide a fail-safe default rather than silently treating it as 0)."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, val))


def _priority_for(score: float) -> str:
    if score >= _HIGH_BAND:
        return "high"
    if score >= _MEDIUM_BAND:
        return "medium"
    return "low"


def _score_chunk(
    chunk: list[dict],
    ai: AIClient,
    reader_context: str,
    instruction: str,
    display_name: str,
    system_rubric: str,
    directive: str,
) -> dict[int, dict]:
    """Return {1-based index: {"score": float, "reason": str}} for one chunk.
    Empty dict on any failure (caller applies a keep-by-default fallback)."""
    context_block = reader_context.strip() if reader_context.strip() else "(no business profile provided)"
    instruction_block = instruction.strip() if instruction.strip() else "(none — use the business profile)"
    prompt = f"""{system_rubric}

READER / BUSINESS CONTEXT:
{context_block}

WHAT {display_name} WANTS TO SEE (instruction):
{instruction_block}

{directive}
Return ONLY a JSON array, one object per item, in order:
[
  {{"index": 1, "score": <number 0-10>, "reason": "<one sentence justifying this score>"}}
]

ITEMS:
{_format_items(chunk)}"""
    try:
        raw = ai.extract_json(prompt)
        decisions = json.loads(raw)
        if not isinstance(decisions, list):
            return {}
    except Exception:
        return {}

    out: dict[int, dict] = {}
    for d in decisions:
        if not isinstance(d, dict):
            continue
        idx = d.get("index")
        if not isinstance(idx, int):
            continue
        out[idx] = {
            "score": _coerce_score(d.get("score")),
            "reason": str(d.get("reason") or "")[:200],
        }
    return out


def score_items(
    items: list[dict],
    ai: AIClient,
    reader_context: str = "",
    instruction: str = "",
    display_name: str = "the executive",
    purpose: str = "relevance",
) -> list[dict]:
    """Attach `ai_score` (float 0-10) + `score_reason` to every item and set
    `priority` from the score band. Returns items sorted by score descending so
    the caller can take the top-N.

    `purpose`:
      - "relevance"  (market_intelligence): score relevance to the reader's business.
        The caller gates by DEFAULT_THRESHOLD (topics aren't pre-curated).
      - "materiality" (company_intelligence): the companies are already user-chosen,
        so score how significant the development is FOR that company. The caller does
        NOT relevance-gate — it keeps each company's top-K (see _apply_company_quota).

    Fail-safe: if a chunk's AI call fails or an item is missing from the response,
    that item keeps a neutral score (= DEFAULT_THRESHOLD) so it survives rather than
    being silently dropped.
    """
    if not items:
        return items

    if purpose == "materiality":
        system_rubric = _MATERIALITY_SYSTEM
        directive = "Score each item 0-10 for how MATERIAL the development is for the company it concerns."
    else:
        system_rubric = _SCORING_SYSTEM
        directive = f"Score each item 0-10 for relevance to {display_name}'s business above."

    for start in range(0, len(items), _CHUNK):
        chunk = items[start:start + _CHUNK]
        decisions = _score_chunk(chunk, ai, reader_context, instruction, display_name,
                                 system_rubric, directive)
        for offset, item in enumerate(chunk):
            decision = decisions.get(offset + 1)
            score = decision["score"] if decision else None
            if score is None:
                # Unscored (AI omitted it or chunk failed) → keep by default.
                score = DEFAULT_THRESHOLD
                reason = (decision or {}).get("reason") or "unscored (kept by default)"
            else:
                reason = decision["reason"]
            item["ai_score"] = score
            item["score_reason"] = reason
            item["priority"] = _priority_for(score)

    items.sort(key=lambda it: it.get("ai_score", 0.0), reverse=True)
    return items
