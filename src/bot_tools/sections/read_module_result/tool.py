import json

IS_ACTION = False


def build(ctx):
    # section_id → (registry list type, canonical id field) for cross-turn addressing.
    _SEC_MAP = {
        "reply_needed":         ("emails", "email_id"),
        "followup_needed":      ("emails", "email_id"),
        "commitments_extract":  ("commitments", "id"),
        "upcoming_commitments": ("commitments", "id"),
        "due_today":            ("commitments", "id"),
    }

    def read_module_result(section_id: str) -> str:
        from src.bot import SECTION_IDS, _with_indices, _register_list
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        try:
            # Commitment lists come from the LIVE store (no snapshot-vs-state drift). The other
            # commitment view, upcoming_commitments, keeps reading its JSON projection because it
            # merges in meeting action items (the store's write_projection keeps it fresh/pruned).
            if section_id in ("commitments_extract", "due_today"):
                from src.modules import commitments_store as store
                from src.modules.tz import today_local_str
                today = today_local_str(ctx.data_dir)
                if section_id == "commitments_extract":
                    items = store.query_visible(ctx.data_dir, today)
                    data = {"id": section_id, "status": "fresh", "items": items}
                else:
                    items = store.query_due_today(ctx.data_dir, today)
                    data = {"id": section_id, "status": "fresh", "date": today, "items": items}
                data["count"] = len(items)
                data["empty"] = not items
            else:
                result_path = ctx.data_dir / "results" / f"{section_id}.json"
                if not result_path.exists():
                    return f"No results for '{section_id}' yet. Run the section first with run_skill()."
                data = json.loads(result_path.read_text())
            if isinstance(data.get("items"), list):
                # Order items to match exactly what the Teams briefing displays, so a "#N" the
                # user saw in a pushed briefing resolves to the same item here.
                try:
                    from src.server import _section_display_order
                    from zoneinfo import ZoneInfo
                    tzname = (ctx.settings or {}).get("timezone") or "UTC"
                    try:
                        tz = ZoneInfo(tzname)
                    except Exception:
                        tz = ZoneInfo("UTC")
                    ordered = _section_display_order(section_id, data, tz)
                except Exception:
                    ordered = data["items"]
                data["items"] = _with_indices(ordered)
                if section_id in _SEC_MAP:
                    _typ, _idf = _SEC_MAP[section_id]
                    _register_list(ctx, _typ, ordered, _idf,
                                   label_fn=lambda it: (it.get("description") or it.get("subject") or "")[:60],
                                   source=section_id)
            if isinstance(data.get("handled"), list):
                data["handled"] = _with_indices(data["handled"])
            print(f"[Bot] read_module_result({section_id})")
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading {section_id}: {e}"
    return read_module_result
