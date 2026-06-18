"""Assembles the three-layer context the chat answers from:

  1. Capability layer (FROZEN)  — the distilled KB pages under kb/. Small enough
     (~15 pages) to inject whole; no retrieval/embeddings needed.
  2. Prompt-current layer (LIVE) — for a question about a section's prompt, the raw
     src/skills/{id}/skill.md, served verbatim (never paraphrased).
  3. Known-issues layer (LIVE)  — open/in-progress entries from requests.json.

Why live layers exist: prompt text and bug status change every commit, so freezing
them into KB prose would make the chat confidently wrong. See kb/KB_GUIDE.md §6.
"""
import os
from pathlib import Path

from . import state

_APP_ROOT = Path(__file__).resolve().parent.parent   # feedback-board/
_REPO_ROOT = _APP_ROOT.parent                          # repo root (local dev)


def _resolve(env_name: str, baked: Path, dev: Path) -> Path:
    """Locate a bundled read-only asset dir. In Docker it's baked next to the app
    (`baked`); in local dev it lives in the repo (`dev`). An explicit env wins.
    This locates assets — it is NOT a user-data fallback (cf. CLAUDE.md principle 1)."""
    override = os.getenv(env_name)
    if override:
        return Path(override)
    return baked if baked.exists() else dev


KB_DIR = _resolve("KB_DIR", _APP_ROOT / "kb", _REPO_ROOT / "kb")
SKILLS_DIR = _resolve("SKILLS_DIR", _APP_ROOT / "skills", _REPO_ROOT / "src" / "skills")

# Natural-language → section_id, so a plain question maps to the right skill.md.
# Only sections that actually have a skill.md are listed.
_SECTION_ALIASES = {
    "ai_summary": ["ai_summary", "ai summary", "morning summary", "morning brief", "briefing", "daily summary"],
    "reply_needed": ["reply_needed", "reply needed", "awaiting reply", "needs reply", "emails to reply"],
    "followup_needed": ["followup_needed", "follow up", "follow-up", "followup", "no response", "sent no response"],
    "commitments_extract": ["commitments_extract", "commitment", "commitments", "promise"],
    "due_today": ["due_today", "due today"],
    "yesterday_recap": ["yesterday_recap", "yesterday", "recap"],
    "meetings_today": ["meetings_today", "meetings today", "today's meetings", "calendar"],
    "m03_meeting": ["m03_meeting", "meeting summary", "meeting transcription", "recording", "transcript", "meeting intelligence"],
    "project_status": ["project_status", "project status"],
    "projects_needing_attention": ["projects_needing_attention", "projects needing attention", "stalled project"],
    "relationship_health": ["relationship_health", "relationship health", "relationship", "cooling"],
    "market_intelligence": ["market_intelligence", "market intelligence", "industry news", "market signal"],
    "company_intelligence": ["company_intelligence", "company intelligence", "company news", "watchlist"],
    "business_insights": ["business_insights", "business insights", "weekly brief", "weekly summary"],
}


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            return text[nl + 1:] if nl != -1 else ""
    return text


def load_index() -> str:
    p = KB_DIR / "index.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load_all_pages() -> str:
    """All capability + architecture page bodies (frontmatter stripped), each
    headed by its path so the model can cite it."""
    chunks = []
    for sub in ("capabilities", "architecture"):
        d = KB_DIR / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            body = _strip_frontmatter(p.read_text(encoding="utf-8")).strip()
            chunks.append(f"### kb/{sub}/{p.name}\n{body}")
    return "\n\n".join(chunks)


def load_skill_raw(section_id: str) -> str | None:
    p = SKILLS_DIR / section_id / "skill.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def match_sections(question: str, limit: int = 3) -> list[str]:
    q = (question or "").lower()
    hits = []
    for sid, aliases in _SECTION_ALIASES.items():
        if any(a in q for a in aliases):
            hits.append(sid)
    return hits[:limit]


def load_open_requests() -> list[dict]:
    return [
        {"id": r["id"], "kind": r["kind"], "title": r["title"], "status": r["status"]}
        for r in state.list_requests()
        if r.get("status") in ("new", "in_progress")
    ]


_PREAMBLE = (
    "You are the internal help assistant for the CEO Platform (an Executive AI "
    "assistant product). You help the internal team understand what the platform "
    "does and how it works.\n\n"
    "RULES:\n"
    "- Answer ONLY from the context blocks below. If the answer isn't covered, say "
    "so plainly (\"That's not documented in the KB\") and suggest filing a request.\n"
    "- Never invent capabilities, prompt text, or bug status.\n"
    "- When asked what a section's current prompt is, quote the CURRENT PROMPT block "
    "verbatim; do not paraphrase it.\n"
    "- For questions about known issues, use the KNOWN ISSUES block.\n"
    "- Be concise and concrete. Cite the kb/ page when useful.\n"
)


def build_prompt(question: str) -> tuple[str, list[str]]:
    """Return (full_prompt, matched_section_ids)."""
    sections = match_sections(question)

    parts = [_PREAMBLE]
    parts.append("=== KB INDEX ===\n" + load_index())
    parts.append("=== KB PAGES (capabilities & architecture) ===\n" + load_all_pages())

    skill_blocks = []
    for sid in sections:
        raw = load_skill_raw(sid)
        if raw:
            skill_blocks.append(f"--- {sid}/skill.md ---\n{raw}")
    if skill_blocks:
        parts.append(
            "=== CURRENT PROMPT(S) (source of truth — quote verbatim, do not paraphrase) ===\n"
            + "\n\n".join(skill_blocks)
        )

    open_reqs = load_open_requests()
    if open_reqs:
        lines = [f"- {r['id']} [{r['kind']}/{r['status']}] {r['title']}" for r in open_reqs]
        parts.append("=== KNOWN ISSUES / OPEN REQUESTS (live registry) ===\n" + "\n".join(lines))

    parts.append("=== QUESTION ===\n" + (question or "").strip())
    return "\n\n".join(parts), sections
