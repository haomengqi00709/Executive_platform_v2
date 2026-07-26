"""
Per-feature Gemini token accounting (P0 — cost visibility).

Why: the platform had NO token logging, so a runaway cost (~CA$1.5k in two weeks)
was invisible until the bill. This records every Gemini call's token usage,
attributed to a (feature, uid) tag the caller sets via a contextvar in src/ai.py,
and aggregates per UTC-day per-feature so you can see EXACTLY where tokens go —
locally (`python -m scripts.measure_tokens run <uid> <feature>`) or in prod
(surfaced in /api/admin/fleet-health → ops dashboard).

Hot-path safe: an in-process accumulator is flushed to disk every FLUSH_EVERY calls
or FLUSH_SECS seconds, so we never read-modify-write a growing JSON on every call.
Records only token COUNTS + a feature name — never prompt text.
"""
import atexit
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Official Gemini pricing (USD), verified 2026-06 against ai.google.dev/gemini-api/docs/pricing.
# The `out` rate INCLUDES thinking tokens (Google bills thinking at the output rate).
# Search differs by model FAMILY: 2.5 bills per grounded REQUEST (fan-out does NOT multiply
# cost); 3.x bills per underlying QUERY (one request fans out into many billed queries).
_MODEL_PRICING = {
    "gemini-2.5-flash": {"in": 0.30 / 1e6, "out": 2.50 / 1e6, "search_unit": "request", "search": 35 / 1000},
    "gemini-3.5-flash": {"in": 1.50 / 1e6, "out": 9.00 / 1e6, "search_unit": "query",   "search": 14 / 1000},
    # Moonshot Kimi (OpenAI-compatible provider). Official platform.moonshot.ai list price
    # 2026-07 ($0.95/M in, $4.00/M out — sources vary $0.60-0.95; priced at the HIGH end so we
    # never under-estimate; reconcile against the Moonshot bill once real traffic flows).
    # No search SKU (Kimi has no grounded search). Also fixes the pre-existing bug where
    # bot_fallback's Kimi rows silently fell back to gemini-3.5-flash pricing.
    "kimi-k2.6": {"in": 0.95 / 1e6, "out": 4.00 / 1e6, "search_unit": "request", "search": 0.0},
    # DeepSeek V4 (OpenAI-compatible, api.deepseek.com), official list price 2026-07.
    # No search SKU. Cache-hit input is far cheaper ($0.0028/M Flash) but we price at the
    # cache-miss rate so we never under-estimate.
    "deepseek-v4-flash": {"in": 0.14 / 1e6, "out": 0.28 / 1e6, "search_unit": "request", "search": 0.0},
    "deepseek-v4-pro":   {"in": 0.435 / 1e6, "out": 0.87 / 1e6, "search_unit": "request", "search": 0.0},
}
# Records that predate model tracking (or use an unknown model) are priced as the pricier
# 3.5 so we never UNDER-estimate (3.5 was the 2026-06 incident default).
_FALLBACK_MODEL = "gemini-3.5-flash"

# 3.5 hides grounding_metadata.web_search_queries, so locally we only ever see grounded
# REQUESTS, not the billed QUERIES they fan out into. When we have no query count, estimate
# queries = requests × this factor. Calibrate it from a finalized SKU day with
# scripts/reconcile_usage.py (SKU queries ÷ GC requests). Env-overridable.
SEARCH_FANOUT = float(os.getenv("GEMINI_SEARCH_FANOUT", "15"))


def _pricing_for(model) -> dict:
    return _MODEL_PRICING.get(model or "", _MODEL_PRICING[_FALLBACK_MODEL])

# Resolve the store path lazily from the app's single source of truth
# (auth.DATA_DIR), so it always matches where the app writes data — even after
# ai.py's load_dotenv(override=True) has set DATA_DIR from .env at import time.
def _store_path() -> Path:
    try:
        from src import auth
        base = auth.DATA_DIR
    except Exception:
        base = Path(os.getenv("DATA_DIR") or (Path(__file__).resolve().parents[2] / ".data"))
    return Path(base) / "_ops" / "token_usage.json"


def _search_log_path() -> Path:
    """Append-only, full record of every grounded call's ACTUAL search queries —
    so we can trace exactly what was searched and reconcile against the Google
    search SKU (count + content), not just an aggregate number."""
    return _store_path().parent / "search_log.jsonl"


def _append_search_log(feature: str, uid: str, queries: list) -> None:
    try:
        p = _search_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).isoformat(),
               "feature": feature, "uid": (uid or "")[:8],
               "n": len(queries), "queries": list(queries)}
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


_FLUSH_EVERY = 10      # flush after this many recorded calls
_FLUSH_SECS  = 15      # ...or this many seconds, whichever comes first
_RETAIN_DAYS = 35      # prune day-buckets older than this on flush

# Print a per-call line to stdout (Railway logs / local console). On by default
# so local measurement is immediately visible; set AI_USAGE_PRINT=0 to silence.
_PRINT = (os.getenv("AI_USAGE_PRINT", "1").strip().lower() not in ("0", "false", "no"))

_lock = threading.Lock()
_pending: dict = {}
_calls_since_flush = 0
_last_flush = time.time()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record(feature: str, uid: str, prompt_tokens: int, output_tokens: int,
           total_tokens: int, is_search: bool = False,
           search_queries: int = 0, queries: list | None = None,
           model: str = "") -> None:
    """Accumulate one Gemini call's usage. Best-effort; never raises into callers.

    search_calls   = grounded REQUESTS (1 per generate_with_search call).
    search_queries = the ACTUAL underlying Google Search queries that call issued
                     (from grounding_metadata.web_search_queries). This is the unit
                     the search SKU bills, so it's what reconciles with the Google
                     bill — and exposes the per-call fan-out (1 request → N queries).
    model          = the Gemini model that served the call; drives per-model pricing
                     in cost_usd (2.5 vs 3.5 differ ~5×). Buckets are nested per model,
                     so a feature that ran on BOTH 2.5 and 3.5 in the same day (e.g. a
                     model comparison) is priced per model, never blended into one."""
    global _calls_since_flush, _last_flush
    try:
        feature = feature or "unknown"
        if _PRINT:
            print(f"[ai.usage] feature={feature} uid={(uid or '')[:8]} model={model or '?'} "
                  f"in={prompt_tokens} out={output_tokens} total={total_tokens} "
                  f"search={int(bool(is_search))} web_queries={int(search_queries or 0)}")
            if queries:
                shown = " | ".join(str(q)[:70] for q in queries[:10])
                print(f"[ai.search] feature={feature} issued {len(queries)} query(ies): {shown}")
        if queries:
            _append_search_log(feature, uid, queries)
        key = (_today(), feature)
        mkey = model or "(unrecorded)"
        do_flush = False
        with _lock:
            by_model = _pending.setdefault(key, {})
            c = by_model.setdefault(mkey, {"prompt": 0, "output": 0, "total": 0,
                                           "search_calls": 0, "search_queries": 0, "calls": 0})
            c["prompt"] += int(prompt_tokens or 0)
            c["output"] += int(output_tokens or 0)
            c["total"]  += int(total_tokens or 0)
            c["search_calls"] += 1 if is_search else 0
            c["search_queries"] += int(search_queries or 0)
            c["calls"]  += 1
            _calls_since_flush += 1
            if _calls_since_flush >= _FLUSH_EVERY or (time.time() - _last_flush) >= _FLUSH_SECS:
                do_flush = True
        # Per-user daily tally (drives the budget breaker + ops dashboard) — this call's
        # cost + tokens (input, and billed output = total − prompt, which includes thinking).
        try:
            from src.modules import budget
            _p = int(prompt_tokens or 0); _t = int(total_tokens or 0)
            _billed_out = max(_t - _p, int(output_tokens or 0))
            _cost = cost_usd({"prompt": _p, "output": int(output_tokens or 0), "total": _t,
                              "search_calls": 1 if is_search else 0,
                              "search_queries": int(search_queries or 0)}, model)
            budget.add_spend(uid, feature, _cost, _p, _billed_out)
        except Exception:
            pass
        if do_flush:
            _flush()
    except Exception:
        pass


def record_failure(feature: str, uid: str, kind: str = "error") -> None:
    """A billable call we could NOT meter — it timed out / errored before returning, so
    there is no usage_metadata to read. Google's server still ran (and billed) it. We can't
    recover the token count locally (only GC/SKU see it); log it so the gap is visible and
    so a meter-vs-GC reconciliation that shows GC > meter is EXPECTED, not a new bug."""
    if _PRINT:
        print(f"[ai.usage] UNMETERED {kind} feature={feature or 'unknown'} uid={(uid or '')[:8]} "
              f"— Google billed it but no usage_metadata was returned (only GC/SKU can see it)")


def _flush() -> None:
    """Merge the in-process accumulator into the on-disk store (concurrency-safe)."""
    global _calls_since_flush, _last_flush
    with _lock:
        pending = dict(_pending)
        _pending.clear()
        _calls_since_flush = 0
        _last_flush = time.time()
    if not pending:
        return
    try:
        from src.storage import file_lock, atomic_write_json
        with file_lock(_store_path()):
            store = {}
            if _store_path().exists():
                try:
                    store = json.loads(_store_path().read_text())
                except Exception:
                    store = {}
            for (date, feature), by_model in pending.items():
                day = store.setdefault(date, {})
                # Migrate any legacy flat bucket → nested {model: bucket}, then merge.
                fdict = _as_by_model(day.get(feature, {}))
                day[feature] = fdict
                for mkey, c in by_model.items():
                    f = fdict.setdefault(mkey, {"prompt": 0, "output": 0, "total": 0,
                                                "search_calls": 0, "search_queries": 0, "calls": 0})
                    for k in ("prompt", "output", "total", "search_calls", "search_queries", "calls"):
                        f[k] = f.get(k, 0) + c.get(k, 0)
            cutoff = datetime.now(timezone.utc).date().toordinal() - _RETAIN_DAYS
            for d in [d for d in list(store) if (_ordinal(d) or 10**9) < cutoff]:
                store.pop(d, None)
            atomic_write_json(_store_path(), store)
    except Exception:
        pass


def _ordinal(date_str: str):
    try:
        return datetime.fromisoformat(date_str).date().toordinal()
    except Exception:
        return None


_BUCKET_KEYS = ("prompt", "output", "total", "search_calls", "search_queries", "calls")


def _as_by_model(fval: dict) -> dict:
    """Normalize a store feature-value into {model: bucket}. Legacy flat buckets (token keys
    at top level, optional 'model' field) are wrapped under their recorded model, so old
    token_usage.json files keep working after the move to per-model nesting."""
    if isinstance(fval, dict) and "prompt" in fval:
        m = fval.get("model") or "(unrecorded)"
        return {m: {k: fval.get(k, 0) for k in _BUCKET_KEYS}}
    return fval or {}


def cost_usd(rec: dict, model: str | None = None) -> float:
    # model: explicit per-bucket model (new nested store). Falls back to rec['model']
    # for legacy flat buckets called as cost_usd(rec).
    p = _pricing_for(model if model is not None else rec.get("model"))
    # Output billing INCLUDES thinking. billed_output = total − prompt (= candidates + thinking).
    # The old formula used candidates-only ("output") and dropped thinking — and thinking is
    # ~half of output tokens — so it under-counted output cost by ~2×. Fall back to "output"
    # only when total is missing/degenerate (e.g. um was None → total 0).
    billed_output = rec.get("total", 0) - rec.get("prompt", 0)
    if billed_output < rec.get("output", 0):
        billed_output = rec.get("output", 0)
    if p["search_unit"] == "query":
        # 3.x: billed per underlying query. We usually can't see 3.5's queries (API hides
        # them), so estimate from grounded requests × the calibrated fan-out. If we DID
        # capture real queries (e.g. on 2.5, or a 3.x call that reported them), use those.
        sq = rec.get("search_queries") or 0
        search_units = sq if sq else rec.get("search_calls", 0) * SEARCH_FANOUT
    else:
        # 2.5: billed per grounded request — fan-out does NOT multiply cost.
        search_units = rec.get("search_calls", 0)
    return round(
        rec.get("prompt", 0) * p["in"]
        + billed_output * p["out"]
        + search_units * p["search"],
        4,
    )


def load_store() -> dict:
    try:
        _flush()
    except Exception:
        pass
    try:
        return json.loads(_store_path().read_text()) if _store_path().exists() else {}
    except Exception:
        return {}


def summary(days: int = 7) -> dict:
    """Per-feature usage with $ estimates over the last `days` (incl. today),
    plus today alone. For fleet-health / the ops dashboard."""
    store = load_store()
    today_ord = datetime.now(timezone.utc).date().toordinal()

    def rollup(window: int) -> dict:
        agg: dict = {}
        cost: dict = {}
        for date, feats in store.items():
            o = _ordinal(date)
            if o is None or o <= today_ord - window:
                continue
            for feat, fval in feats.items():
                a = agg.setdefault(feat, {"prompt": 0, "output": 0, "total": 0,
                                          "search_calls": 0, "search_queries": 0, "calls": 0})
                # Price each (day, feature, MODEL) sub-bucket with its own model, then sum —
                # so a feature that ran on both 2.5 and 3.5 (same day or across a switch) is
                # costed correctly per model rather than blended.
                for mkey, rec in _as_by_model(fval).items():
                    for k in a:
                        a[k] += rec.get(k, 0)
                    cost[feat] = cost.get(feat, 0.0) + cost_usd(rec, mkey)
        feats_out = [{"feature": f, **r, "est_usd": round(cost.get(f, 0.0), 4)}
                     for f, r in sorted(agg.items(), key=lambda kv: -cost.get(kv[0], 0.0))]
        return {"features": feats_out,
                "est_usd_total": round(sum(cost.values()), 2)}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today":   rollup(1),
        "last_7d": rollup(days),
    }


def reset() -> None:
    """Clear all accounting (for a clean local measurement run)."""
    global _pending, _calls_since_flush
    with _lock:
        _pending = {}
        _calls_since_flush = 0
    try:
        if _store_path().exists():
            _store_path().unlink()
    except Exception:
        pass


atexit.register(_flush)
