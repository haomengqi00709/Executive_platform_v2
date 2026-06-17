#!/usr/bin/env python3
"""Pull a project's Gemini usage from Cloud Monitoring, attributed by API key.

  python -m scripts.key_usage --project 168552037856 [--key-uid <uid>] [--hours 6]

Shows generativelanguage request_count grouped by credential_id (API key) +
response_code, and output-token count by model, over the window.

NOTE: per-key gives REQUEST counts (200/429/…), not tokens/$ — token metrics carry
only `model`, and $ is billed per-PROJECT. So isolate cost with a separate project
(this is why the local test key lives in its own project). Requires `gcloud auth`.
"""
import argparse
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

_MON = "https://monitoring.googleapis.com/v3/projects"


def _token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"],
                          capture_output=True, text=True).stdout.strip()


def _query(project: str, tok: str, metric: str, start: str, end: str, period: int):
    params = {
        "filter": f'metric.type="{metric}" AND resource.labels.service="generativelanguage.googleapis.com"',
        "interval.startTime": start, "interval.endTime": end,
        "aggregation.alignmentPeriod": f"{period}s", "aggregation.perSeriesAligner": "ALIGN_SUM",
    }
    req = urllib.request.Request(f"{_MON}/{project}/timeSeries?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:
        return None, str(e)
    if "error" in d:
        return None, d["error"].get("message", "")
    return d.get("timeSeries", []), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--key-uid", default=None, help="filter to one API key UID")
    ap.add_argument("--hours", type=float, default=6)
    a = ap.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=a.hours)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    period = max(60, int(a.hours * 3600))
    tok = _token()
    print(f"project {a.project} · last {a.hours}h · {iso(start)} → {iso(end)}")

    # Requests by API key (credential_id) + response code
    ts, err = _query(a.project, tok, "serviceruntime.googleapis.com/api/request_count",
                     iso(start), iso(end), period)
    print("\n=== requests by API key ===")
    if err:
        print("  err:", err[:120])
    elif not ts:
        print("  (no requests)")
    else:
        agg = {}
        for s in ts:
            cred = s.get("resource", {}).get("labels", {}).get("credential_id", "(none)")
            code = s.get("metric", {}).get("labels", {}).get("response_code", "?")
            if a.key_uid and a.key_uid not in cred:
                continue
            n = sum(int(p["value"].get("int64Value", 0)) for p in s.get("points", []))
            agg.setdefault(cred, {})[code] = agg.setdefault(cred, {}).get(code, 0) + n
        for cred, codes in sorted(agg.items()):
            tot = sum(codes.values())
            extra = " ".join(f"{k}={v}" for k, v in sorted(codes.items()) if k != "200")
            print(f"  {cred}: total={tot} ok(200)={codes.get('200',0)} {extra}")

    # Output tokens by model (not per-key — model only)
    ts, err = _query(a.project, tok, "generativelanguage.googleapis.com/generate_content_usage_output_token_count",
                     iso(start), iso(end), period)
    print("\n=== output tokens by model (incl thinking) ===")
    if err:
        print("  err:", err[:120])
    elif not ts:
        print("  (none)")
    else:
        by = {}
        for s in ts:
            m = s.get("metric", {}).get("labels", {}).get("model", "?")
            by[m] = by.get(m, 0) + sum(int(p["value"].get("int64Value", 0)) for p in s.get("points", []))
        for m, n in sorted(by.items(), key=lambda x: -x[1]):
            print(f"  {m}: {n:,} output tok")


if __name__ == "__main__":
    main()
