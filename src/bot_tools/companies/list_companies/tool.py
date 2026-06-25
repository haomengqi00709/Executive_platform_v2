import json

IS_ACTION = False

# Mirror company_intelligence.py so "what am I tracking for intelligence" matches what actually runs.
_MONITORED_STATUSES = frozenset({"client", "prospect", "partner", "investor"})
_PRANK = {"high": 0, "medium": 1, "low": 2}


def build(ctx):
    def list_companies(only_monitored: bool = True, status: str = "", priority: str = "", limit: int = 25) -> str:
        """List the companies in the user's database (derived from CRM + Projects + manual adds)."""
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.bot import _with_indices, _register_list
            from src.modules.companies import load_companies
            comps = load_companies(data_dir).get("companies", {})
            st, pr = status.strip().lower(), priority.strip().lower()
            rows = []
            for key, c in comps.items():
                # only_monitored mirrors the company_intelligence filter: what intelligence ACTUALLY runs on.
                if only_monitored:
                    if not c.get("monitor_intelligence") or c.get("ignore"):
                        continue
                    if (c.get("derived_status") or "other") not in _MONITORED_STATUSES and not c.get("manual"):
                        continue
                if st and (c.get("derived_status") or "").lower() != st:
                    continue
                if pr and (c.get("priority") or "").lower() != pr:
                    continue
                rows.append({
                    "key": key, "name": c.get("name", key), "status": c.get("derived_status", ""),
                    "priority": c.get("priority", ""), "monitor_intelligence": bool(c.get("monitor_intelligence")),
                    "manual": bool(c.get("manual")), "contact_count": c.get("contact_count", 0),
                })
            rows.sort(key=lambda r: (r.get("name") or "").lower())
            rows.sort(key=lambda r: _PRANK.get((r.get("priority") or "medium").lower(), 1))
            total = len(rows)
            rows = _with_indices(rows[:max(1, limit)])
            _register_list(ctx, "companies", rows, "key",
                           label_fn=lambda it: f'{it.get("name")} [{it.get("status") or "—"}/{it.get("priority") or "—"}]',
                           source="companies")
            scope = "monitored-for-intelligence" if only_monitored else "all"
            print(f"[Bot] list_companies({scope}{(' status='+st) if st else ''}{(' priority='+pr) if pr else ''}) → {len(rows)}/{total}")
            return json.dumps({"scope": scope, "shown": len(rows), "total": total, "companies": rows},
                              ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return list_companies
