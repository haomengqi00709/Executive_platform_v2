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
        result_path = ctx.data_dir / "results" / f"{section_id}.json"
        if not result_path.exists():
            return f"No results for '{section_id}' yet. Run the section first with run_skill()."
        try:
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
