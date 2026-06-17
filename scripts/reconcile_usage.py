#!/usr/bin/env python3
"""Reconcile the THREE token/cost sources so you can trust each one for what it's good at.

  python -m scripts.reconcile_usage --project gen-lang-client-0448678985 --hours 24 \
      [--sku-search-usd 25.75] [--sku-search-queries 1839] [--data-dir .data]

Why three sources (see docs/token-measurement-method.md):
  1. OUR METER  (.data/_ops/token_usage.json) — real-time, per-FEATURE. Accurate per captured
     call, but blind to failed/timeout calls and to 3.5's hidden search queries.
  2. GC Cloud Monitoring — Google's server-side USAGE truth (catches every call), per-model,
     but search is counted as REQUESTS (not billed queries) and it can't break down by feature.
  3. SKU billing — the authoritative $ and the real billed QUERY count, but lags ~1 day and
     (without a BigQuery export) is read off the console by hand → pass it in via --sku-* flags.

This script lines them up: meter-vs-GC output gap (= coverage holes), per-model $ from GC at
official prices, and — if you paste a finalized SKU search line — the real search FAN-OUT
(SKU queries ÷ GC grounded requests), which is the multiplier to set GEMINI_SEARCH_FANOUT to.
"""
import argparse
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.modules import token_usage  # noqa: E402

_MON = "https://monitoring.googleapis.com/v3/projects"
_OUT_METRIC   = "generativelanguage.googleapis.com/generate_content_usage_output_token_count"
_SEARCH_METRIC = "generativelanguage.googleapis.com/quota/generate_content_search_request_usage/usage"
_IN_METRIC    = "generativelanguage.googleapis.com/quota/generate_content_paid_tier_2_input_token_count/usage"


def _token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True).stdout.strip()


def _gc(project, tok, metric, start, end, period):
    params = {
        "filter": f'metric.type="{metric}"',
        "interval.startTime": start, "interval.endTime": end,
        "aggregation.alignmentPeriod": f"{period}s", "aggregation.perSeriesAligner": "ALIGN_SUM",
        "aggregation.crossSeriesReducer": "REDUCE_SUM", "aggregation.groupByFields": "metric.labels.model",
    }
    req = urllib.request.Request(f"{_MON}/{project}/timeSeries?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": f"Bearer {tok}"})
    out = {}
    try:
        d = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:
        return {}, str(e)
    if "error" in d:
        return {}, d["error"].get("message", "")[:100]
    for s in d.get("timeSeries", []):
        m = s.get("metric", {}).get("labels", {}).get("model", "?")
        n = 0
        for p in s.get("points", []):
            v = p["value"]
            n += int(v.get("int64Value", 0)) if "int64Value" in v else float(v.get("doubleValue", 0))
        out[m] = out.get(m, 0) + n
    return out, None


def _price(model_key: str) -> dict:
    # model_key from GC may be "gemini-3.5-flash" (token metrics) or "gemini-3" (search). Map both.
    if "3" in model_key:
        return token_usage._MODEL_PRICING["gemini-3.5-flash"]
    return token_usage._MODEL_PRICING["gemini-2.5-flash"]


def _meter_window(days: int) -> dict:
    """Sum our meter's buckets over the last `days` UTC days, grouped by model."""
    store = token_usage.load_store()
    cutoff = datetime.now(timezone.utc).date().toordinal() - days
    agg = {}
    for date, feats in store.items():
        try:
            o = datetime.fromisoformat(date).date().toordinal()
        except Exception:
            continue
        if o <= cutoff:
            continue
        for fval in feats.values():
            for m, rec in token_usage._as_by_model(fval).items():
                a = agg.setdefault(m, {"prompt": 0, "billed_output": 0, "search_calls": 0, "search_queries": 0, "usd": 0.0})
                a["prompt"] += rec.get("prompt", 0)
                a["billed_output"] += max(rec.get("total", 0) - rec.get("prompt", 0), rec.get("output", 0))
                a["search_calls"] += rec.get("search_calls", 0)
                a["search_queries"] += rec.get("search_queries", 0)
                a["usd"] += token_usage.cost_usd(rec, m)
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--data-dir", default=None, help="point the meter at this .data (default: repo .data)")
    ap.add_argument("--sku-search-usd", type=float, default=None, help="finalized SKU search $ for the window")
    ap.add_argument("--sku-search-queries", type=int, default=None, help="finalized SKU billed query count")
    a = ap.parse_args()

    from src import auth
    auth.DATA_DIR = Path(a.data_dir).expanduser().resolve() if a.data_dir \
        else Path(__file__).resolve().parents[1] / ".data"

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=a.hours)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    period = max(60, int(a.hours * 3600))
    tok = _token()
    print(f"project {a.project} · window {iso(start)} → {iso(end)} ({a.hours}h)\n")

    # ── GC (authoritative usage) ──
    out_by, e1 = _gc(a.project, tok, _OUT_METRIC, iso(start), iso(end), period)
    srch_by, e2 = _gc(a.project, tok, _SEARCH_METRIC, iso(start), iso(end), period)
    in_by, e3 = _gc(a.project, tok, _IN_METRIC, iso(start), iso(end), period)

    print("=== GC Cloud Monitoring (server-side usage truth) ===")
    if e1:
        print("  output: err", e1)
    gc_usd = 0.0
    for m, out in sorted(out_by.items()):
        p = _price(m)
        inp = in_by.get(m, 0)
        usd = inp * p["in"] + out * p["out"]   # token $ only (search added below)
        gc_usd += usd
        print(f"  {m}: output={int(out):,} tok  input≈{int(inp):,} (paid_tier_2,口径偏高)  → token ${usd:.3f}")
    print(f"  search requests by model: " + (", ".join(f"{k}={int(v)}" for k, v in sorted(srch_by.items())) or "(none)"))
    if e3:
        print(f"  (input metric note: {e3})")

    # ── OUR METER (real-time, per-feature) ──
    print("\n=== Our meter (.data/_ops/token_usage.json, last {}d) ===".format(max(1, round(a.hours / 24))))
    meter = _meter_window(max(1, round(a.hours / 24)))
    meter_usd = sum(v["usd"] for v in meter.values())
    meter_out = sum(v["billed_output"] for v in meter.values())
    if not meter:
        print("  (no meter data in window)")
    for m, v in sorted(meter.items()):
        print(f"  {m}: billed_output={v['billed_output']:,} tok  search_calls={v['search_calls']} "
              f"search_q={v['search_queries']}  → est ${v['usd']:.3f}")

    # ── Reconciliation ──
    gc_out = sum(out_by.values())
    print("\n=== Reconciliation ===")
    if gc_out:
        gap = 1 - (meter_out / gc_out) if gc_out else 0
        print(f"  output:  meter {int(meter_out):,}  vs  GC {int(gc_out):,}  → meter captures "
              f"{100*meter_out/gc_out:.0f}% (gap {100*gap:.0f}% = failed/uncovered calls)")
    if a.sku_search_usd is not None or a.sku_search_queries is not None:
        gc_3x_req = sum(v for k, v in srch_by.items() if "3" in k)
        sku_q = a.sku_search_queries
        if sku_q is None and a.sku_search_usd is not None:
            sku_q = round(a.sku_search_usd / (14 / 1000))   # $14/1000 queries
        print(f"  search:  SKU {sku_q} billed queries  vs  GC {int(gc_3x_req)} grounded requests (3.x)")
        if gc_3x_req:
            fan = sku_q / gc_3x_req
            print(f"           → FAN-OUT ≈ {fan:.1f}×   (set GEMINI_SEARCH_FANOUT={fan:.0f} to calibrate the meter's 3.x search estimate)")
        if a.sku_search_usd is not None:
            print(f"           SKU search $ = ${a.sku_search_usd:.2f}  (authoritative; our estimate uses FANOUT={token_usage.SEARCH_FANOUT})")
    else:
        print("  search:  pass --sku-search-usd / --sku-search-queries from a finalized SKU day to lock the fan-out")
    print("\n  TRUST: token $ → GC (above) is the usage truth; per-feature → our meter; final $ + real query count → SKU.")


if __name__ == "__main__":
    main()
