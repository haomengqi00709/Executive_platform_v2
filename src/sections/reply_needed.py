"""
reply_needed section — emails awaiting a reply from the executive.

Four-layer input:
  1. src/skills/reply_needed.md        — system skill description
  2. data_dir/instructions/reply_needed.md — user instructions (optional)
  3. Screened inbox (last 7 days), with sent-folder already-replied filter
  4. CRM + Projects DB context injected per email
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.screener import screen_emails
from src.modules.crm import load_crm
from src.modules.projects import load_projects
from src.modules.validator import validate_output
from src.modules.tz import now_local, today_local_str
from src.modules.profile import load_profile_context

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "reply_needed" / "skill.md"
_BATCH_SIZE = 8
_MAX_PROJECTS_PER_EMAIL = 3


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / "reply_needed.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _find_projects_for_email(
    sender_email: str,
    subject: str,
    preview: str,
    all_projects: list[dict],
) -> list[dict]:
    """
    Match projects to an email using two strategies:
      1. Exact: sender email is in project.participants
      2. Fuzzy: subject or preview contains a project key_topic word
    Returns up to _MAX_PROJECTS_PER_EMAIL matches.
    """
    sender_lower = sender_email.lower()
    text_lower = (subject + " " + preview).lower()

    matched: dict[str, dict] = {}

    for p in all_projects:
        if p.get("ignore") or p.get("archived") or p.get("priority") == "ignore" or p.get("status") == "completed":
            continue
        pid = p.get("id", "")

        # Exact match
        participants = [e.lower() for e in p.get("participants", [])]
        if sender_lower in participants:
            matched[pid] = p
            continue

        # Fuzzy match via key_topics
        for topic in p.get("key_topics", []):
            if len(topic) >= 4 and topic.lower() in text_lower:
                matched[pid] = p
                break

    result = list(matched.values())[:_MAX_PROJECTS_PER_EMAIL]
    return result


def _build_email_context_block(
    index: int,
    msg: dict,
    crm_contacts: dict,
    all_projects: list[dict],
    today_str: str,
) -> str:
    """Build the per-email context block injected into the AI prompt."""
    subject = (msg.get("subject") or "(no subject)")[:120]
    from_obj = (msg.get("from") or {}).get("emailAddress") or {}
    from_name = from_obj.get("name", "")
    from_email = from_obj.get("address", "").lower()
    received = (msg.get("receivedDateTime") or "")[:10]
    preview = (msg.get("bodyPreview") or "")[:250]

    lines = [
        f"EMAIL #{index}",
        f"Subject: {subject}",
        f"From: {from_name} <{from_email}> | Received: {received}",
        f"Preview: {preview}",
    ]

    # CRM context
    contact = crm_contacts.get(from_email)
    if contact:
        last_contact = contact.get("last_contact", "unknown")
        try:
            from datetime import date
            today = date.fromisoformat(today_str)
            delta = (today - date.fromisoformat(last_contact)).days
            days_ago = f" ({delta} days ago)"
        except Exception:
            days_ago = ""

        lines.append("")
        lines.append("CONTACT (from CRM):")
        lines.append(f"  Company: {contact.get('company', '')} | Role: {contact.get('role', '')} | Status: {contact.get('status', '')}")
        lines.append(f"  Last contact: {last_contact}{days_ago}")
        if contact.get("summary"):
            lines.append(f"  History: {contact['summary']}")
        if contact.get("writing_style"):
            lines.append(f"  Writing style: {contact['writing_style']}")

    # Project context
    matched_projects = _find_projects_for_email(from_email, subject, preview, all_projects)
    for proj in matched_projects:
        lines.append("")
        lines.append(f"RELATED PROJECT:")
        lines.append(
            f"  {proj.get('name', '')} ({proj.get('category', '')}) | "
            f"Status: {proj.get('status', '')} | Momentum: {proj.get('momentum', '')}"
        )
        if proj.get("summary"):
            lines.append(f"  Summary: {proj['summary']}")
        if proj.get("next_action"):
            lines.append(f"  Next action: {proj['next_action']}")
        if proj.get("key_topics"):
            lines.append(f"  Key topics: {', '.join(proj['key_topics'])}")

    return "\n".join(lines)


def _analyze_batch(
    batch: list[tuple[int, dict, str]],  # (index, msg, context_block)
    skill_text: str,
    ai: AIClient,
    display_name: str,
    date_str: str,
    user_instruction: str,
) -> list[dict]:
    """Send a batch to Gemini, return list of AI assessment dicts."""
    emails_block = "\n\n---\n\n".join(ctx for _, _, ctx in batch)

    prompt = (
        skill_text
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{emails_with_context}", emails_block)
        .replace(
            "{user_instruction}",
            user_instruction if user_instruction else "(none)",
        )
    )

    try:
        raw = ai.generate(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        return parsed
    except Exception as e:
        print(f"[ReplyNeeded] Batch analysis failed: {e}")
        return []


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
) -> dict:
    """
    Scan inbox for emails needing a reply, enriched with CRM + project context.

    Returns standard section result dict.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}
    display_name = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir)
    date_str = now_local(data_dir).strftime("%A, %B %d, %Y")
    today_str = today_local_str(data_dir)

    # ── 1. Skill + user instruction ───────────────────────
    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""
    instruction_path = data_dir / "instructions" / "reply_needed.md"
    user_instruction = instruction_path.read_text().strip() if instruction_path.exists() else ""

    # ── 2. Load CRM + Projects DB ─────────────────────────
    log("Loading CRM and Projects DB...")
    crm_data = load_crm(data_dir)
    crm_contacts = crm_data.get("contacts", {})
    ignored_emails: set = {
        email for email, c in crm_contacts.items()
        if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore"
    }

    projects_db = load_projects(data_dir)
    all_projects = list(projects_db.get("projects", {}).values())

    # ── 3. Fetch inbox ────────────────────────────────────
    log("Fetching inbox (last 14 days)...")
    try:
        raw_messages = graph.get_messages_since(days=14, max_results=200)
    except Exception as e:
        log(f"Inbox fetch failed: {e}")
        raw_messages = []

    # ── 4. Screen emails ──────────────────────────────────
    if raw_messages:
        log(f"Screening {len(raw_messages)} emails...")
        screened = screen_emails(
            messages=raw_messages,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=business_context,
            display_name=display_name,
            progress=progress,
        )
        visible = [m for m in screened if not m.get("screened_out")]
    else:
        visible = []

    log(f"{len(visible)} emails passed screening")

    # ── 5. Already-replied filter ─────────────────────────
    log("Checking sent folder for already-replied threads...")
    try:
        sent_msgs = graph.get_sent_messages_since(days=14, max_results=100)
        sent_conv_ids = {m.get("conversationId") for m in sent_msgs if m.get("conversationId")}
    except Exception as e:
        log(f"Sent folder fetch failed: {e}")
        sent_conv_ids = set()

    log("Checking drafts folder (user-started but unsent replies)...")
    try:
        draft_msgs = graph.get_drafts_since(days=14, max_results=100)
        draft_conv_ids = {m.get("conversationId") for m in draft_msgs if m.get("conversationId")}
    except Exception as e:
        log(f"Drafts folder fetch failed: {e}")
        draft_conv_ids = set()

    # Already-handled filter: replied (SentItems) OR drafted (Drafts)
    handled_conv_ids = sent_conv_ids | draft_conv_ids
    not_replied = [
        m for m in visible
        if m.get("conversationId") not in handled_conv_ids
    ]

    # Skip emails the user sent to themselves
    own_email = (settings.get("report_email") or settings.get("username") or "").lower()
    if own_email:
        not_replied = [
            m for m in not_replied
            if ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower() != own_email
        ]

    # Deduplicate by conversationId — keep most recent per thread
    seen_convs: dict[str, dict] = {}
    for m in not_replied:
        cid = m.get("conversationId") or m.get("id", "")
        existing = seen_convs.get(cid)
        if not existing or (m.get("receivedDateTime", "") > existing.get("receivedDateTime", "")):
            seen_convs[cid] = m

    # Secondary dedup by (normalised subject + sender email) — catches same email sent multiple times
    seen_subj_sender: dict[str, dict] = {}
    for m in seen_convs.values():
        subj = re.sub(r"\s+", " ", (m.get("subject") or "").lower().strip())
        sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
        key = f"{subj}||{sender}"
        existing = seen_subj_sender.get(key)
        if not existing or (m.get("receivedDateTime", "") > existing.get("receivedDateTime", "")):
            seen_subj_sender[key] = m
    emails_to_review = list(seen_subj_sender.values())

    log(f"{len(emails_to_review)} emails after already-replied + dedup filter")

    if not emails_to_review:
        result = {
            "id": "reply_needed",
            "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "items": [],
            "count": 0,
            "empty": True,
        }
        _save_result(data_dir, result)
        return result

    # ── 6. Build context blocks ───────────────────────────
    log("Building contact and project context for each email...")
    indexed: list[tuple[int, dict, str]] = []
    for i, msg in enumerate(emails_to_review, start=1):
        ctx = _build_email_context_block(i, msg, crm_contacts, all_projects, today_str)
        indexed.append((i, msg, ctx))

    # ── 7. AI batch analysis ──────────────────────────────
    ai_assessments: dict[int, dict] = {}
    batches = [indexed[i:i + _BATCH_SIZE] for i in range(0, len(indexed), _BATCH_SIZE)]
    for b_num, batch in enumerate(batches, 1):
        log(f"Analyzing batch {b_num}/{len(batches)} ({len(batch)} emails)...")
        assessments = _analyze_batch(batch, skill_text, ai, display_name, date_str, user_instruction)
        for a in assessments:
            idx = a.get("email_index")
            if idx:
                ai_assessments[idx] = a

    # ── 8. Assemble results ───────────────────────────────
    items = []
    for i, msg, _ in indexed:
        assessment = ai_assessments.get(i, {})
        if not assessment.get("needs_reply", True):
            continue

        from_obj = (msg.get("from") or {}).get("emailAddress") or {}
        from_email = from_obj.get("address", "").lower()
        from_name = from_obj.get("name", "")

        contact = crm_contacts.get(from_email)
        contact_summary = None
        if contact:
            contact_summary = {
                "name":          contact.get("name", from_name),
                "company":       contact.get("company", ""),
                "role":          contact.get("role", ""),
                "status":        contact.get("status", ""),
                "last_contact":  contact.get("last_contact", ""),
                "writing_style": contact.get("writing_style", ""),
            }

        matched_projects = _find_projects_for_email(
            from_email,
            msg.get("subject", ""),
            msg.get("bodyPreview", ""),
            all_projects,
        )
        project_summaries = [
            {
                "id":          p.get("id", ""),
                "name":        p.get("name", ""),
                "status":      p.get("status", ""),
                "momentum":    p.get("momentum", ""),
                "summary":     p.get("summary", ""),
                "next_action": p.get("next_action", ""),
            }
            for p in matched_projects
        ]

        items.append({
            "email_id":         msg.get("id", ""),
            "subject":          (msg.get("subject") or "(no subject)")[:200],
            "from_email":       from_email,
            "from_name":        from_name,
            "received":         msg.get("receivedDateTime", ""),
            "preview":          (msg.get("bodyPreview") or "")[:300],
            "priority":         assessment.get("priority", "medium"),
            "reason":           assessment.get("reason", ""),
            "reply_tone":       assessment.get("reply_tone", "formal"),
            "suggested_opening": assessment.get("suggested_opening", ""),
            "contact":          contact_summary,
            "projects":         project_summaries,
            "digested_at":      "",
        })

    # ── 9. Validator Agent ────────────────────────────────
    if items:
        log(f"Validator reviewing {len(items)} candidates...")
        items = validate_output(
            items=items,
            ai=ai,
            section_id="reply_needed",
            user_instruction=user_instruction,
            display_name=display_name,
            date_str=date_str,
        )
        log(f"{len(items)} emails remain after validation")

    # Sort: high → medium → low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))

    # Preserve digested_at across scans — emails already mentioned in a Teams
    # digest must keep that marker so they aren't repeated.
    prior_path = data_dir / "results" / "reply_needed.json"
    if prior_path.exists():
        try:
            prior = json.loads(prior_path.read_text())
            prior_digested = {
                it.get("email_id"): it.get("digested_at", "")
                for it in (prior.get("items") or [])
                if it.get("email_id") and it.get("digested_at")
            }
            for it in items:
                eid = it.get("email_id")
                if eid in prior_digested:
                    it["digested_at"] = prior_digested[eid]
        except Exception:
            pass

    result = {
        "id":       "reply_needed",
        "status":   "fresh",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }

    _save_result(data_dir, result)
    log(f"Reply needed done — {len(items)} emails need a reply ({sum(1 for x in items if x['priority'] == 'high')} high priority)")
    return result
