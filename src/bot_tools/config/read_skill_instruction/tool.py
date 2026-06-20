IS_ACTION = False


def build(ctx):
    def read_skill_instruction(section_id: str) -> str:
        from src.bot import SECTION_IDS
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        path = ctx.data_dir / "instructions" / f"{section_id}.md"
        content = path.read_text().strip() if path.exists() else ""
        print(f"[Bot] read_skill_instruction({section_id})")
        return content if content else "(no custom instructions yet)"
    return read_skill_instruction
