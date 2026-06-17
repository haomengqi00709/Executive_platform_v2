#!/usr/bin/env python3
"""
Local per-feature Gemini token measurement (P0).

Run a single feature for one user with a (cheap, capped) test GEMINI_API_KEY and
see EXACTLY how many tokens / dollars it burned — without spending on production.

Usage (from repo root):
  python -m scripts.measure_tokens report               # show today's per-feature $/tokens
  python -m scripts.measure_tokens reset                # clear the counters
  python -m scripts.measure_tokens run <uid> <feature>  # run one feature, then report

  <feature> = a section id (reply_needed, followup_needed, commitments_extract,
              ai_summary, company_intelligence, market_intelligence, relationship_health,
              yesterday_recap, ...) OR  crm_refresh  OR  projects_refresh

Tip: measure cleanly with
  python -m scripts.measure_tokens reset
  python -m scripts.measure_tokens run <uid> reply_needed
  python -m scripts.measure_tokens run <uid> company_intelligence
  python -m scripts.measure_tokens report
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import token_usage  # noqa: E402

# AI-using features worth measuring (sections + the two heavy refreshes).
_ALL_FEATURES = [
    "reply_needed", "followup_needed", "commitments_extract", "ai_summary",
    "yesterday_recap", "relationship_health", "business_insights",
    "market_intelligence", "company_intelligence", "crm_refresh", "projects_refresh",
]


def _print_report() -> None:
    s = token_usage.summary()
    for label in ("today", "last_7d"):
        block = s[label]
        print(f"\n=== {label}  (est ${block['est_usd_total']}) ===")
        if not block["features"]:
            print("  (no usage recorded)")
            continue
        print(f"  {'feature':<26} {'calls':>6} {'in':>12} {'out':>12} {'srch':>5} {'web_q':>6} {'$':>9}")
        for f in block["features"]:
            print(f"  {f['feature']:<26} {f['calls']:>6} {f['prompt']:>12,} "
                  f"{f['output']:>12,} {f['search_calls']:>5} {f.get('search_queries', 0):>6} {f['est_usd']:>9.3f}")


def _run_feature(uid: str, feature: str) -> None:
    from src import auth
    from src.graph import GraphClient
    from src.ai import AIClient, usage_context

    data_dir = auth.DATA_DIR / uid
    if not data_dir.exists():
        print(f"No data dir for uid {uid} ({data_dir})"); return

    print(f"Running '{feature}' for {uid[:8]} (tagged for accounting)...")
    token = auth.get_valid_access_token(uid)
    graph = GraphClient(token)
    ai = AIClient()
    settings = {}
    sp = data_dir / "settings.json"
    if sp.exists():
        import json
        try:
            settings = json.loads(sp.read_text())
        except Exception:
            pass

    with usage_context(feature, uid):
        if feature == "crm_refresh":
            from src.modules.crm import refresh_crm, save_crm
            seg = (data_dir / "context" / "market_segments.md")
            save_crm(data_dir, refresh_crm(graph, ai, data_dir,
                                           business_context=settings.get("business_context", "")))
        elif feature in ("projects_refresh", "projects"):
            from src.modules.projects import refresh_projects, save_projects
            save_projects(data_dir, refresh_projects(graph, ai, data_dir, settings=settings))
        else:
            import importlib
            mod = importlib.import_module(f"src.sections.{feature}")
            result = mod.run(graph, ai, data_dir, settings, None)
            print(f"  → {result.get('count', '?')} items, status={result.get('status')}")
    print("Done.")


def main() -> None:
    argv = list(sys.argv[1:])

    # The repo .env sets DATA_DIR=/app/.data (the container path), and ai.py's
    # load_dotenv(override=True) forces it — which is wrong for local runs. So
    # point at the repo's real local .data here (override with --data-dir <path>).
    data_dir = None
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        data_dir = Path(argv[i + 1]).expanduser().resolve()
        del argv[i:i + 2]
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[1] / ".data"

    from src import auth
    auth.DATA_DIR = data_dir   # token_usage + feature runs both follow this
    print(f"[measure] DATA_DIR = {data_dir}  (exists={data_dir.exists()})")

    if not argv or argv[0] == "report":
        _print_report(); return
    if argv[0] == "reset":
        token_usage.reset(); print("token usage reset."); return
    if argv[0] == "run" and len(argv) >= 3:
        try:
            _run_feature(argv[1], argv[2])
        except Exception as e:
            print(f"[measure] '{argv[2]}' errored (partial usage still recorded): {e}")
        token_usage._flush()
        _print_report(); return
    if argv[0] == "runall" and len(argv) >= 2:
        uid = argv[1]
        budget = float(argv[2]) if len(argv) >= 3 else 1.9
        for f in _ALL_FEATURES:
            print(f"\n########## {f} ##########", flush=True)
            try:
                _run_feature(uid, f)
            except Exception as e:
                print(f"[measure] '{f}' errored (partial usage still recorded): {e}")
            token_usage._flush()
            cum = token_usage.summary()["today"]["est_usd_total"]
            print(f">>> 累计 ${cum}  (跑完 {f})", flush=True)
            if cum >= budget:
                print(f">>> 🛑 STOP: 累计 ${cum} ≥ 阈值 ${budget} — 不再跑后续模块", flush=True)
                break
        _print_report(); return
    print(__doc__)


if __name__ == "__main__":
    main()
