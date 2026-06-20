IS_ACTION = False


def build(ctx):
    def update_skill_instruction(section_id: str, content: str) -> str:
        from src.bot import SECTION_IDS
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        path = ctx.data_dir / "instructions" / f"{section_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"[Bot] update_skill_instruction({section_id}) → {len(content)} chars")
        return f"✅ Instructions updated for: {SECTION_IDS[section_id].split(' — ')[0]}"
    return update_skill_instruction
