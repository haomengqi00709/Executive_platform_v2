"""
profile_init — AI-generated first-time profile drafts.

Runs after CRM build and Projects build complete. Reads:
  - User's own sent emails (full body) → extract signature → user's title, company, links
  - CRM contacts' role field → frequency map → who the user serves
  - Projects' key_topics field → what work the user does

Produces two markdown drafts that go into profile/business_profile.md and
profile/market_segments.md. The user reviews them on the Onboarding page.
"""
import json
import re
from collections import Counter
from html import unescape
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.profile import (
    save_business_profile,
    save_market_segments,
)

_SIGNATURE_SAMPLES = 8   # how many recent sent emails to look at
_MAX_BODY_CHARS = 3000   # truncate each body so the prompt stays reasonable


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _collect_signatures(graph: GraphClient, log) -> list[str]:
    """Pull recent sent emails, return the trailing ~600 chars of each body (where signatures live)."""
    try:
        raw = graph.get_messages(
            top=_SIGNATURE_SAMPLES,
            folder="SentItems",
            orderby="sentDateTime desc",
        )
    except Exception as e:
        log(f"sent-email fetch failed: {e}")
        return []

    samples = []
    for msg in raw:
        body = msg.get("body") or {}
        content = body.get("content") or ""
        if body.get("contentType", "").lower() == "html":
            content = _strip_html(content)
        content = content[:_MAX_BODY_CHARS].strip()
        if content:
            # signatures live at the tail — keep the last 600 chars for the prompt
            samples.append(content[-600:])
    return samples


def _collect_crm_titles(data_dir: Path) -> list[tuple[str, int]]:
    crm_path = Path(data_dir) / "crm.json"
    if not crm_path.exists():
        return []
    try:
        crm = json.loads(crm_path.read_text())
    except Exception:
        return []

    titles = Counter()
    for c in crm.get("contacts", {}).values():
        if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore":
            continue
        if c.get("status") not in ("client", "prospect", "partner", "investor"):
            continue
        role = (c.get("role") or "").strip()
        if role:
            titles[role] += 1
    return titles.most_common(15)


def _collect_project_topics(data_dir: Path) -> list[tuple[str, int]]:
    proj_path = Path(data_dir) / "projects.json"
    if not proj_path.exists():
        return []
    try:
        projs = json.loads(proj_path.read_text())
    except Exception:
        return []

    topics = Counter()
    for p in projs.get("projects", {}).values():
        if p.get("ignore") or p.get("archived"):
            continue
        for t in p.get("key_topics", []) or []:
            t = (t or "").strip()
            if t:
                topics[t] += 1
    return topics.most_common(20)


def _build_prompt(
    display_name: str,
    user_email: str,
    signatures: list[str],
    crm_titles: list[tuple[str, int]],
    project_topics: list[tuple[str, int]],
) -> str:
    sig_block = "\n---\n".join(signatures) if signatures else "(no signature samples found)"
    titles_block = "\n".join(f"- {t} ({n})" for t, n in crm_titles) or "(no CRM titles yet)"
    topics_block = "\n".join(f"- {t} ({n})" for t, n in project_topics) or "(no project topics yet)"

    return f"""You are drafting the foundational business profile for {display_name} (email: {user_email}).
This profile is the long-lived context layer that every AI feature on the platform reads —
market intelligence searches, email triage, company intelligence, daily briefings, and chat.
Get it right and the platform sharpens; leave it vague and everything downstream is generic.

Below is everything we know so far from analysing the user's mailbox.

## Signature samples (last {_SIGNATURE_SAMPLES} sent emails — look at the tail of each)
{sig_block}

## Top contact titles from CRM (clients, prospects, partners only)
{titles_block}

## Recurring topics across active projects
{topics_block}

---

Produce TWO markdown drafts the user will review.

### 1. business_profile.md
Sections (use these exact H2 headers):
- What the company does
- Scale and stage
- Typical customers
- Current strategic focus
- Competitors and adjacent players

### 2. market_segments.md
Sections (use these exact H2 headers):
- Primary segments
- Secondary / adjacent segments
- Geographic markets
- Segments to ignore

Rules:
- Lead each H2 with a concrete inferred answer based on the data above. Do not hedge.
- When the data does not support a confident answer, write a single bullet: `- (Confirm with user)` so they know to fill it in.
- Keep each section to 2-4 short bullet points or 1-3 sentences. The user will edit, so write tight.
- Do not invent specific revenue numbers, headcounts, or client names that aren't in the data.
- Write the body in plain English, not telegraphic notes.

Return a JSON object with two string keys:
{{
  "business_profile": "# Business Profile\\n\\n## What the company does\\n...",
  "market_segments":  "# Market Segments\\n\\n## Primary segments\\n..."
}}
"""


def run_profile_init(
    data_dir: Path,
    graph: GraphClient,
    ai: AIClient,
    settings: dict,
    progress=None,
) -> dict:
    """
    Generates business_profile.md and market_segments.md drafts from existing data.
    Writes drafts to disk. Status management is the caller's responsibility —
    this function does NOT modify init_status.json.

    Returns the two drafts as a dict for logging/inspection.
    """
    data_dir = Path(data_dir)

    def log(msg: str):
        if progress:
            progress(msg)
        print(f"[profile_init] {msg}")

    log("Starting profile generation...")

    display_name = settings.get("display_name") or "the executive"
    user_email   = settings.get("report_email") or settings.get("username") or ""

    signatures = _collect_signatures(graph, log)
    log(f"Collected {len(signatures)} signature samples")

    crm_titles = _collect_crm_titles(data_dir)
    log(f"Collected {len(crm_titles)} CRM title patterns")

    project_topics = _collect_project_topics(data_dir)
    log(f"Collected {len(project_topics)} project topic keywords")

    prompt = _build_prompt(display_name, user_email, signatures, crm_titles, project_topics)
    raw = ai.extract_json(prompt)

    try:
        data = json.loads(raw)
    except Exception as e:
        log(f"AI returned invalid JSON ({e}); leaving default templates in place")
        return {"business_profile": "", "market_segments": ""}

    business = (data.get("business_profile") or "").strip()
    segments = (data.get("market_segments") or "").strip()

    if business:
        save_business_profile(data_dir, business)
        log(f"Wrote business_profile.md ({len(business)} chars)")
    if segments:
        save_market_segments(data_dir, segments)
        log(f"Wrote market_segments.md ({len(segments)} chars)")

    log("Done")
    return {"business_profile": business, "market_segments": segments}
