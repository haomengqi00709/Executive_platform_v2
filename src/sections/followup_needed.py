"""
followup_needed section — sent emails with no reply yet.

Four-layer input:
  1. src/skills/followup_needed/skill.md   — system skill description
  2. data_dir/instructions/followup_needed.md — user instructions (optional)
  3. Sent folder (last 14 days), filtered against inbox conversationIds
  4. CRM + Projects DB context injected per email (keyed on recipient, not sender)
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.crm import load_crm
from src.modules.projects import load_projects
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "followup_needed" / "skill.md"
_BATCH_SIZE = 8
_MAX_PROJECTS_PER_EMAIL = 3


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / "followup_needed.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _days_since(sent_str: str) -> int:
    try:
        sent_dt = datetime.fromisoformat(sent_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - sent_dt
        return max(0, delta.days)
    except Exception:
        return 0


def _get_primary_recipient(msg: dict) -> tuple[str, str]:
    """Return (email, name) of the first toRecipient."""
    recipients = msg.get("toRecipients") or []
    if recipients:
        addr = (recipients[0].get("emailAddress") or {})
        return addr.get("address", "").lower(), addr.get("name", "")
    return "", ""


def _find_projects_for_email(
    recipient_email: str,
    subject: str,
    preview: str,
    all_projects: list[dict],
) -> list[dict]:
    recipient_lower = recipient_email.lower()
    text_lower = (subject + " " + preview).lower()
    matched: dict[str, dict] = {}
    for p in all_projects:
        if p.get("ignore") or p.get("priority") == "ignore" or p.get("status") == "completed":
            continue
        pid = p.get("id", "")
        participants = [e.lower() for e in p.get("participants", [])]
        if recipient_lower in participants:
            matched[pid] = p
            continue
        for topic in p.get("key_topics", []):
            if len(topic) >= 4 and topic.lower() in text_lower:
                matched[pid] = p
                break
    return list(matched.values())[:_MAX_PROJECTS_PER_EMAIL]


def _build_email_context_block(
    index: int,
    msg: dict,
    crm_contacts: dict,
    all_projects: list[dict],
) -> str:
    subject = (msg.get("subject") or "(no subject)")[:120]
    to_email, to_name = _get_primary_recipient(msg)
    sent = (msg.get("sentDateTime") or msg.get("lastModifiedDateTime") or "")[:10]
    preview = (msg.get("bodyPreview") or "")[:250]
    days = _days_since(msg.get("sentDateTime") or "")

    lines = [
        f"EMAIL #{index}",
        f"Subject: {subject}",
        f"To: {to_name} <{to_email}> | Sent: {sent} ({days} days ago, no reply)",
        f"Preview: {preview}",
    ]

    contact = crm_contacts.get(to_email)
    if contact:
        last_contact = contact.get("last_contact", "unknown")
        lines.append("")
        lines.append("CONTACT (from CRM):")
        lines.append(f"  Company: {contact.get('company', '')} | Role: {contact.get('role', '')} | Status: {contact.get('status', '')}")
        lines.append(f"  Last contact: {last_contact}")
        if contact.get("summary"):
            lines.append(f"  History: {contact['summary']}")
        if contact.get("writing_style"):
            lines.append(f"  Writing style: {contact['writing_style']}")

    matched_projects = _find_projects_for_email(to_email, subject, preview, all_projects)
    for proj in matched_projects:
        lines.append("")
        lines.append("RELATED PROJECT:")
        lines.append(
            f"  {proj.get('name', '')} ({proj.get('category', '')}) | "
            f"Status: {proj.get('status', '')} | Momentum: {proj.get('momentum', '')}"
        )
        if proj.get("summary"):
            lines.append(f"  Summary: {proj['summary']}")
        if proj.get("next_action"):
            lines.append(f"  Next action: {proj['next_action']}")

    return "\n".join(lines)


def _analyze_batch(
    batch: list[tuple[int, dict, str]],
    skill_text: str,
    ai: AIClient,
    display_name: str,
    date_str: str,
    user_instruction: str,
) -> list[dict]:
    emails_block = "\n\n---\n\n".join(ctx for _, _, ctx in batch)
    prompt = (
        skill_text
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{emails_with_context}", emails_block)
        .replace("{user_instruction}", user_instruction if user_instruction else "(none)")
    )
    try:
        raw = ai.generate(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception as e:
        print(f"[FollowupNeeded] Batch analysis failed: {e}")
        return []


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
) -> dict:
    """
    Find sent emails with no reply, enriched with CRM + project context.
    Returns standard section result dict.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}
    display_name = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir)
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    own_email = (settings.get("report_email") or settings.get("username") or "").lower()
    bot_emails: set = {e.lower() for e in (settings.get("bot_emails") or [])}

    # ── 1. Skill + user instruction ───────────────────────
    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""
    instruction_path = data_dir / "instructions" / "followup_needed.md"
    user_instruction = instruction_path.read_text().strip() if instruction_path.exists() else ""

    # ── 2. Load CRM + Projects DB ─────────────────────────
    log("Loading CRM and Projects DB...")
    crm_data = load_crm(data_dir)
    crm_contacts = crm_data.get("contacts", {})
    ignored_emails: set = {
        email for email, c in crm_contacts.items()
        if c.get("ignore") or c.get("priority") == "ignore"
    }

    projects_db = load_projects(data_dir)
    all_projects = list(projects_db.get("projects", {}).values())

    # ── 3. Fetch inbox conversationIds (metadata only, no AI) ─
    # We only need to know which threads got a reply — no body content needed.
    log("Fetching inbox metadata (last 14 days) to check for replies...")
    try:
        inbox_meta = graph.get_inbox_metadata_since(days=14, max_results=300)
    except Exception as e:
        log(f"Inbox metadata fetch failed: {e}")
        inbox_meta = []

    # Map conversationId → latest received date in inbox
    inbox_conv_latest: dict[str, str] = {}
    for m in inbox_meta:
        cid = m.get("conversationId")
        received = m.get("receivedDateTime") or ""
        if cid and received:
            if received > inbox_conv_latest.get(cid, ""):
                inbox_conv_latest[cid] = received
    log(f"{len(inbox_conv_latest)} inbox conversationIds found")

    # ── 4. Fetch sent emails ──────────────────────────────
    log("Fetching sent emails (last 14 days)...")
    try:
        sent_msgs = graph.get_sent_messages_since(days=14, max_results=200)
    except Exception as e:
        log(f"Sent fetch failed: {e}")
        sent_msgs = []

    # ── 5. No-reply filter ────────────────────────────────
    # A sent email has "no reply" only if there's no inbox message received AFTER the sent time.
    # Can't just check conversationId existence — the original received email shares the same
    # conversationId and may still be sitting in the inbox.
    def _has_reply_after(sent_msg: dict) -> bool:
        cid = sent_msg.get("conversationId")
        sent_dt = sent_msg.get("sentDateTime") or ""
        if not cid or not sent_dt:
            return False
        latest_received = inbox_conv_latest.get(cid, "")
        return latest_received > sent_dt

    no_reply = [m for m in sent_msgs if not _has_reply_after(m)]

    # Skip emails sent to yourself
    if own_email:
        no_reply = [
            m for m in no_reply
            if _get_primary_recipient(m)[0] != own_email
        ]

    # Skip emails to ignored CRM contacts
    no_reply = [
        m for m in no_reply
        if _get_primary_recipient(m)[0] not in ignored_emails
    ]

    # Skip emails to configured bot/AI assistant accounts (e.g. pre-meeting brief senders)
    if bot_emails:
        no_reply = [
            m for m in no_reply
            if _get_primary_recipient(m)[0] not in bot_emails
        ]

    # ── 6. Dedup by conversationId, then subject+recipient ─
    seen_convs: dict[str, dict] = {}
    for m in no_reply:
        cid = m.get("conversationId") or m.get("id", "")
        existing = seen_convs.get(cid)
        sent_dt = m.get("sentDateTime") or ""
        if not existing or sent_dt > (existing.get("sentDateTime") or ""):
            seen_convs[cid] = m

    seen_subj_recip: dict[str, dict] = {}
    for m in seen_convs.values():
        subj = re.sub(r"\s+", " ", (m.get("subject") or "").lower().strip())
        to_email, _ = _get_primary_recipient(m)
        key = f"{subj}||{to_email}"
        existing = seen_subj_recip.get(key)
        sent_dt = m.get("sentDateTime") or ""
        if not existing or sent_dt > (existing.get("sentDateTime") or ""):
            seen_subj_recip[key] = m

    emails_to_review = list(seen_subj_recip.values())
    log(f"{len(emails_to_review)} sent emails without a reply")

    if not emails_to_review:
        result = {
            "id": "followup_needed", "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "items": [], "count": 0, "empty": True,
        }
        _save_result(data_dir, result)
        return result

    # ── 7. Build context blocks ───────────────────────────
    log("Building recipient context for each email...")
    indexed: list[tuple[int, dict, str]] = []
    for i, msg in enumerate(emails_to_review, start=1):
        ctx = _build_email_context_block(i, msg, crm_contacts, all_projects)
        indexed.append((i, msg, ctx))

    # ── 8. AI batch analysis ──────────────────────────────
    ai_assessments: dict[int, dict] = {}
    batches = [indexed[i:i + _BATCH_SIZE] for i in range(0, len(indexed), _BATCH_SIZE)]
    for b_num, batch in enumerate(batches, 1):
        log(f"Analyzing batch {b_num}/{len(batches)} ({len(batch)} emails)...")
        assessments = _analyze_batch(batch, skill_text, ai, display_name, date_str, user_instruction)
        for a in assessments:
            idx = a.get("email_index")
            if idx:
                ai_assessments[idx] = a

    # ── 9. Assemble results ───────────────────────────────
    items = []
    for i, msg, _ in indexed:
        assessment = ai_assessments.get(i, {})
        if not assessment.get("needs_followup", True):
            continue

        to_email, to_name = _get_primary_recipient(msg)
        days = assessment.get("days_waiting") or _days_since(msg.get("sentDateTime") or "")

        contact = crm_contacts.get(to_email)
        contact_summary = None
        if contact:
            contact_summary = {
                "name":          contact.get("name", to_name),
                "company":       contact.get("company", ""),
                "role":          contact.get("role", ""),
                "status":        contact.get("status", ""),
                "last_contact":  contact.get("last_contact", ""),
                "writing_style": contact.get("writing_style", ""),
            }

        matched_projects = _find_projects_for_email(
            to_email, msg.get("subject", ""), msg.get("bodyPreview", ""), all_projects,
        )
        project_summaries = [
            {
                "id": p.get("id", ""), "name": p.get("name", ""),
                "status": p.get("status", ""), "momentum": p.get("momentum", ""),
                "summary": p.get("summary", ""), "next_action": p.get("next_action", ""),
            }
            for p in matched_projects
        ]

        items.append({
            "email_id":          msg.get("id", ""),
            "subject":           (msg.get("subject") or "(no subject)")[:200],
            "to_email":          to_email,
            "to_name":           to_name,
            "sent":              msg.get("sentDateTime", ""),
            "preview":           (msg.get("bodyPreview") or "")[:300],
            "days_waiting":      days,
            "urgency":           assessment.get("urgency", "medium"),
            "reason":            assessment.get("reason", ""),
            "suggested_approach": assessment.get("suggested_approach", ""),
            "contact":           contact_summary,
            "projects":          project_summaries,
        })

    # ── 10. Validator ─────────────────────────────────────
    if items:
        log(f"Validator reviewing {len(items)} candidates...")
        items = validate_output(
            items=items,
            ai=ai,
            section_id="followup_needed",
            user_instruction=user_instruction,
            display_name=display_name,
            date_str=date_str,
        )
        log(f"{len(items)} emails remain after validation")

    # Sort: high → medium → low, then by days_waiting desc
    urgency_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (urgency_order.get(x.get("urgency", "medium"), 1), -x.get("days_waiting", 0)))

    result = {
        "id":       "followup_needed",
        "status":   "fresh",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "items":    items,
        "count":    len(items),
        "empty":    len(items) == 0,
    }
    _save_result(data_dir, result)
    log(f"Follow-up needed done — {len(items)} emails ({sum(1 for x in items if x['urgency'] == 'high')} high urgency)")
    return result
