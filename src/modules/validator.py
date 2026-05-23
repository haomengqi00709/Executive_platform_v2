"""
Validator Agent — 通用二次审核模块，所有 section 共用。

第一个 AI 处理大量信息（邮件 + CRM + Project 上下文），容易出错。
Validator 只看最终小列表（5-20条），专注做一件事：这条对不对。

用法：
    from src.modules.validator import validate_output
    items = validate_output(items, ai, section_id="reply_needed",
                            user_instruction=..., display_name=..., date_str=...)

规则文件位置：src/skills/validators/{section_id}.md
失败时返回原始列表（fail-safe，不影响 section 正常运行）。
"""
import json
import re
from datetime import datetime
from pathlib import Path

from src.ai import AIClient

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

_SECTION_TITLES = {
    "reply_needed":        "Reply Needed list",
    "followup_needed":     "Follow-up Needed list",
    "commitments_extract": "Commitments list",
    "upcoming_commitments": "Upcoming Commitments list",
    "market_intelligence":  "Market Intelligence list",
    "company_intelligence": "Company Intelligence list",
    "invoices_contracts":  "Invoices & Contracts list",
    "relationship_health": "Relationship Health list",
    "business_insights":   "Business Insights list",
    "project_status":              "Project Status list",
    "projects_needing_attention":  "Projects Needing Attention list",
    "meetings_today":              "Today's Meetings list",
    "due_today":                   "Due Today list",
    "yesterday_recap":             "Yesterday's Recap list",
}


def _load_skill_doc(section_id: str) -> str:
    path = _SKILLS_DIR / section_id / "skill.md"
    if path.exists():
        return path.read_text().strip()
    return ""


def _load_validator_rules(section_id: str) -> str:
    path = _SKILLS_DIR / section_id / "validator.md"
    if path.exists():
        return path.read_text().strip()
    return ""


def _format_items_for_review(items: list[dict], section_id: str) -> str:
    """Format items as a compact list for the validator prompt."""
    lines = []
    for i, item in enumerate(items, start=1):
        if section_id == "reply_needed":
            subject = (item.get("subject") or "(no subject)")[:80]
            from_name = item.get("from_name") or item.get("from_email") or "—"
            priority = item.get("priority", "medium").upper()
            reason = (item.get("reason") or "")[:120]
            lines.append(f"[{i}] Subject: \"{subject}\" | From: {from_name} | Priority: {priority}")
            if reason:
                lines.append(f"     Reason: \"{reason}\"")
        elif section_id == "followup_needed":
            tag = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(
                item.get("urgency", "medium"), "[MED]"
            )
            subject = (item.get("subject") or "(no subject)")[:80]
            to = item.get("to_name") or item.get("to_email") or "—"
            days = item.get("days_waiting", 0)
            reason = (item.get("reason") or "")[:80]
            lines.append(f"[{i}] {tag} \"{subject}\" → {to} ({days}d waiting) | {reason}")
        elif section_id == "commitments_extract":
            ctype = "ME" if item.get("type") == "my_commitment" else "THEM"
            desc = (item.get("description") or "")[:100]
            contact = item.get("contact_name") or item.get("contact_email") or "—"
            due = item.get("due_date") or "no deadline"
            confidence = item.get("due_date_confidence", "none")
            priority = item.get("priority", "medium").upper()
            lines.append(
                f"[{i}] [{ctype}] {desc} → {contact} | Due: {due} ({confidence}) | Priority: {priority}"
            )
        elif section_id == "company_intelligence":
            signal = item.get("signal_type", "other").upper()
            company = (item.get("company") or "—")[:50]
            headline = (item.get("headline") or "(no headline)")[:80]
            person = item.get("person") or "—"
            priority = item.get("priority", "medium").upper()
            lines.append(f"[{i}] [{signal}] {company} — {headline} | {person} | {priority}")
            summary = (item.get("summary") or "")[:120]
            if summary:
                lines.append(f"     Summary: \"{summary}\"")
        elif section_id == "market_intelligence":
            signal = item.get("signal_type", "other").upper()
            headline = (item.get("headline") or "(no headline)")[:100]
            source = item.get("source") or "—"
            priority = item.get("priority", "medium").upper()
            lines.append(f"[{i}] [{signal}] {headline} | {source} | {priority}")
            summary = (item.get("summary") or "")[:120]
            if summary:
                lines.append(f"     Summary: \"{summary}\"")
        elif section_id == "project_status":
            name = (item.get("name") or "(unnamed)")[:80]
            status = item.get("status", "")
            momentum = item.get("momentum", "")
            category = item.get("category", "")
            last = item.get("last_activity", "")
            lines.append(f"[{i}] [{status.upper()}/{category}] {name} | {momentum} momentum | last {last}")
        elif section_id == "projects_needing_attention":
            name = (item.get("name") or "(unnamed)")[:80]
            status = item.get("status", "")
            momentum = item.get("momentum", "")
            category = item.get("category", "")
            last = item.get("last_activity", "")
            priority = item.get("priority", "medium").upper()
            lines.append(f"[{i}] [{status.upper()}/{category}] {name} | {momentum} momentum | last {last} | {priority}")
            summary = (item.get("summary") or "")[:150]
            if summary:
                lines.append(f"     Summary: \"{summary}\"")
            next_action = (item.get("next_action") or "")[:120]
            if next_action:
                lines.append(f"     Next action: \"{next_action}\"")
        elif section_id == "meetings_today":
            subject = (item.get("subject") or "(no subject)")[:80]
            start = item.get("start_time") or ""
            end = item.get("end_time") or ""
            location = (item.get("location") or "")[:40]
            ac = item.get("attendee_count", 0)
            time_str = (f"{start}–{end}" if start and end else (start or "all-day"))
            lines.append(f"[{i}] {time_str} | {subject} | {ac} attendee(s)" + (f" | {location}" if location else ""))
        elif section_id == "due_today":
            ctype = "ME" if item.get("type") == "my_commitment" else "THEM"
            desc = (item.get("description") or "")[:120]
            contact = item.get("contact_name") or item.get("contact_email") or "—"
            priority = item.get("priority", "medium").upper()
            lines.append(f"[{i}] [{ctype}/{priority}] {desc} → {contact}")
        elif section_id == "yesterday_recap":
            itype = item.get("type", "?")
            if itype == "inbound_email":
                lines.append(f"[{i}] [INBOUND {item.get('time','')}] \"{(item.get('subject') or '')[:80]}\" — from {item.get('from','—')}")
            elif itype == "outbound_email":
                lines.append(f"[{i}] [OUTBOUND {item.get('time','')}] \"{(item.get('subject') or '')[:80]}\" → {item.get('to','—')}")
            elif itype == "meeting":
                rng = f"{item.get('start','')}–{item.get('end','')}"
                ac = len(item.get("attendees", []))
                lines.append(f"[{i}] [MEETING {rng}] {(item.get('subject') or '')[:80]} | {ac} attendee(s)")
            elif itype == "commitment":
                kind = "ME" if item.get("commit_kind") == "my_commitment" else "THEM"
                due = item.get("due_date") or "no deadline"
                lines.append(f"[{i}] [COMMITMENT/{kind}] {(item.get('description') or '')[:100]} (due {due})")
            else:
                lines.append(f"[{i}] [{itype.upper()}] {str(item)[:100]}")
        else:
            # Generic fallback for other sections
            label = (
                item.get("subject") or item.get("title") or
                item.get("name") or item.get("action") or str(item)[:80]
            )
            priority = item.get("priority", "")
            priority_str = f" | Priority: {priority.upper()}" if priority else ""
            lines.append(f"[{i}] {label}{priority_str}")
        lines.append("")
    return "\n".join(lines).strip()


def validate_output(
    items: list[dict],
    ai: AIClient,
    section_id: str,
    user_instruction: str = "",
    display_name: str = "the executive",
    date_str: str = "",
    extra_context: str = "",
) -> list[dict]:
    """
    Second-pass quality review of AI-generated section output.

    Loads section-specific validator rules from src/skills/validators/{section_id}.md,
    applies user instructions, and returns a cleaned list.
    Falls back to original items if parsing fails.
    """
    if not items:
        return items

    if not date_str:
        date_str = datetime.now().strftime("%A, %B %d, %Y")

    skill_doc       = _load_skill_doc(section_id)
    validator_rules = _load_validator_rules(section_id)
    section_title   = _SECTION_TITLES.get(section_id, f"{section_id} list")
    formatted       = _format_items_for_review(items, section_id)
    n               = len(items)

    instruction_block = user_instruction.strip() if user_instruction.strip() else "(none — use common sense)"
    extra_block       = f"\nADDITIONAL CONTEXT:\n{extra_context}\n" if extra_context.strip() else ""
    skill_block       = f"\n--- SECTION PURPOSE & WORKFLOW ---\n{skill_doc}\n--- END ---\n" if skill_doc else ""
    rules_block       = f"\n--- VALIDATOR RULES ---\n{validator_rules}\n--- END ---\n" if validator_rules else ""

    prompt = f"""You are a quality reviewer for {display_name}'s {section_title}.
Today is {date_str}.

Your job: review the candidate list below and remove anything that does not belong,
or correct priorities that are clearly wrong.
{skill_block}{rules_block}
--- USER INSTRUCTIONS (highest priority — always enforce, override everything above) ---
{instruction_block}
--- END ---
{extra_block}
--- CANDIDATE LIST ({n} items) ---
{formatted}
--- END ---

Review every item. For each one:
1. Should it be KEPT or REMOVED? Use the section purpose, validator rules, and user instructions above.
2. If kept, is the priority correct? Adjust if clearly wrong.

Return a JSON array with exactly {n} objects — one per item, in order:
[
  {{
    "index": 1,
    "keep": true,
    "adjusted_priority": "high",
    "removal_reason": ""
  }},
  ...
]

- "index": matches [N] in the candidate list
- "keep": true or false
- "adjusted_priority": original value if unchanged; "high"/"medium"/"low" if adjusting
- "removal_reason": brief reason if keep=false, empty string if keep=true
- Include ALL {n} items
"""

    try:
        raw = ai.extract_json(prompt)
        decisions = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(decisions, list):
            print(f"[Validator:{section_id}] Unexpected response type — returning original")
            return items

        # Build index → decision map
        decision_map: dict[int, dict] = {d.get("index"): d for d in decisions if isinstance(d, dict)}

        validated = []
        for i, item in enumerate(items, start=1):
            decision = decision_map.get(i)
            if decision is None:
                # AI didn't include this item — keep it (fail-safe)
                validated.append(item)
                continue
            if not decision.get("keep", True):
                reason = decision.get("removal_reason", "")
                print(f"[Validator:{section_id}] Removed [{i}]: {reason}")
                continue
            # Apply priority adjustment if present
            adj = decision.get("adjusted_priority", "")
            if adj and adj in ("high", "medium", "low") and adj != item.get("priority"):
                item = {**item, "priority": adj}
            validated.append(item)

        print(f"[Validator:{section_id}] {len(items)} → {len(validated)} items after review")
        return validated

    except Exception as e:
        print(f"[Validator:{section_id}] Failed ({e}) — returning original {len(items)} items")
        return items
