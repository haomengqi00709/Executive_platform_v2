import json

IS_ACTION = False


def build(ctx):
    def read_module_result(section_id: str) -> str:
        from src.bot import SECTION_IDS, _with_indices
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        result_path = ctx.data_dir / "results" / f"{section_id}.json"
        if not result_path.exists():
            return f"No results for '{section_id}' yet. Run the section first with run_skill()."
        try:
            data = json.loads(result_path.read_text())
            if isinstance(data.get("items"), list):
                data["items"] = _with_indices(data["items"])
            if isinstance(data.get("handled"), list):
                data["handled"] = _with_indices(data["handled"])
            print(f"[Bot] read_module_result({section_id})")
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading {section_id}: {e}"
    return read_module_result
