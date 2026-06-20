IS_ACTION = False


def build(ctx):
    def run_skill(section_id: str) -> str:
        from src.bot import SECTION_IDS
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"

        owner_uid = ctx.state.get("owner_uid", "")
        if not owner_uid:
            return "Cannot run section — owner user ID not found in bot state."

        def _run():
            try:
                from src.server import _run_section_for_user
                _run_section_for_user(owner_uid, section_id)
            except Exception as e:
                print(f"[Bot] run_skill {section_id} error: {e}")

        import threading
        threading.Thread(target=_run, daemon=True).start()
        label = SECTION_IDS[section_id].split(" — ")[0]
        print(f"[Bot] run_skill({section_id}) → started")
        return f"✅ {label} is running. Results will appear in your dashboard shortly."
    return run_skill
