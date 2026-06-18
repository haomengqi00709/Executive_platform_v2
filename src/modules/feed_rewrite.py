"""
feed_rewrite — reshape raw feed items into the brief's strategic-insight format.

Feed items (RSS / Google News / HN / Reddit) arrive as raw news: headline = the
article title, summary = a web excerpt, signal_type = "other". The validator
enforces the section standard — headline must be a STRATEGIC INSIGHT (not a news
headline), summary must be CEO-framed, signal_type must be a real category — so
raw feed items get filtered out for "poor quality / not a strategic insight".

This pass (run after the relevance gate, before dedup/quota/validator) rewrites
ONLY the feed-origin survivors into that format, so they compete on equal footing
with grounding items instead of being thrown out for formatting. Grounding items
(origin != "feed") are left untouched. Fail-safe: if the AI step fails, items are
returned unchanged (they may still be dropped by the validator, but nothing is
lost or fabricated).
"""
import json

from src.ai import AIClient

_CHUNK = 8
_VALID_SIGNALS = ("regulatory", "funding", "M&A", "technology", "competitive", "macro", "other")


def _noop(_msg: str) -> None:
    pass


def _rewrite_chunk(chunk: list[dict], ai: AIClient, display_name: str, reader_context: str) -> dict[int, dict]:
    ctx = reader_context.strip() or "(no business profile provided)"
    lines = []
    for i, it in enumerate(chunk, start=1):
        lines.append(f"[{i}] TITLE: {it.get('headline','')}\n     EXCERPT: {(it.get('summary') or '')[:300]}\n     SOURCE: {it.get('source','')}")
    prompt = f"""You are preparing a market-intelligence brief for {display_name}. Below are RAW news items
pulled from feeds. Rewrite each into the brief's house style so it reads like a trusted advisor's
signal, NOT a news headline.

READER / BUSINESS CONTEXT (frame relevance to this business):
{ctx}

For each item produce:
- headline: a sharp STRATEGIC INSIGHT that leads with the implication — not the original news title.
  e.g. instead of "Company X raises $50M", write "Competitor X's $50M raise signals intensifying
  pressure in <space> — watch for <implication>."
- summary: 2-4 sentences for a CEO decision-maker (what happened, why it matters, what it signals).
- signal_type: exactly one of {", ".join(_VALID_SIGNALS)}.

Base everything ONLY on the title + excerpt given — do not invent facts.

ITEMS:
{chr(10).join(lines)}

Return ONLY a JSON array, one object per item, in order:
[{{"index": 1, "headline": "<insight>", "summary": "<2-4 sentences>", "signal_type": "<category>"}}]"""
    try:
        result = json.loads(ai.extract_json(prompt))
        if not isinstance(result, list):
            return {}
    except Exception:
        return {}
    out: dict[int, dict] = {}
    for d in result:
        if isinstance(d, dict) and isinstance(d.get("index"), int):
            out[d["index"]] = d
    return out


def rewrite_feed_items(
    items: list[dict],
    ai: AIClient,
    display_name: str = "the executive",
    reader_context: str = "",
    log=None,
) -> list[dict]:
    """Rewrite feed-origin items in place to the strategic-insight format.
    Grounding items pass through untouched. Returns the full list."""
    log = log or _noop
    feed_idx = [i for i, it in enumerate(items) if it.get("origin") == "feed"]
    if not feed_idx:
        return items

    log(f"rewriting {len(feed_idx)} feed item(s) to brief format")
    rewritten = 0
    for start in range(0, len(feed_idx), _CHUNK):
        batch_idx = feed_idx[start:start + _CHUNK]
        batch = [items[i] for i in batch_idx]
        decisions = _rewrite_chunk(batch, ai, display_name, reader_context)
        for offset, item_i in enumerate(batch_idx):
            d = decisions.get(offset + 1)
            if not d:
                continue
            new_headline = str(d.get("headline") or "").strip()
            new_summary = str(d.get("summary") or "").strip()
            new_signal = d.get("signal_type")
            if new_headline:
                items[item_i]["headline"] = new_headline[:200]
            if new_summary:
                items[item_i]["summary"] = new_summary[:600]
            if new_signal in _VALID_SIGNALS:
                items[item_i]["signal_type"] = new_signal
            rewritten += 1

    log(f"rewrote {rewritten}/{len(feed_idx)} feed items")
    return items
