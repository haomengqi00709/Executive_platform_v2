"""
commitments_extract section — actionable commitments from inbox emails.

Two types:
  my_commitment  — {display_name} agreed to do something / asked to do something
  their_commitment — the other party agreed to do something

Downstream sections that read this file:
  due_today          — filters due_date == today
  upcoming_commitments — combines with calendar, looks ahead 7 days
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.screener import screen_emails
from src.modules.crm import load_crm
from src.modules.projects import load_projects
from src.modules.profile import load_profile_context
from src.modules.validator import validate_output
from src.modules.commitments_state import (
    load_state, save_state, should_show, expire_asked, mark_asked,
)
from src.modules.commitments_cache import (
    load_cache, save_cache, prune_cache, get_last_processed,
    add_email_result, flatten_commitments,
)

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "commitments_extract" / "skill.md"
_BATCH_SIZE = 8
_MAX_PROJECTS_PER_EMAIL = 3


def _save_result(data_dir: Path, result: dict) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    f = results_dir / "commitments_extract.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _commitment_id(email_id: str, ctype: str, description: str) -> str:
    key = f"{email_id}:{ctype}:{description[:40]}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _normalize_desc(description: str) -> str:
    return re.sub(r"\s+", " ", description.lower().strip())[:50]


def _get_sender(msg: dict) -> tuple[str, str]:
    addr = (msg.get("from") or {}).get("emailAddress") or {}
    return addr.get("address", "").lower(), addr.get("name", "")


def _find_projects_for_email(
    sender_email: str,
    subject: str,
    preview: str,
    all_projects: list[dict],
) -> list[dict]:
    sender_lower = sender_email.lower()
    text_lower = (subject + " " + preview).lower()
    matched: dict[str, dict] = {}
    for p in all_projects:
        if p.get("ignore") or p.get("archived") or p.get("priority") == "ignore" or p.get("status") == "completed":
            continue
        pid = p.get("id", "")
        participants = [e.lower() for e in p.get("participants", [])]
        if sender_lower in participants:
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
    from_email, from_name = _get_sender(msg)
    received = (msg.get("receivedDateTime") or "")[:10]
    preview = (msg.get("bodyPreview") or "")[:300]

    lines = [
        f"EMAIL #{index}",
        f"Subject: {subject}",
        f"From: {from_name} <{from_email}> | Received: {received}",
        f"Preview: {preview}",
    ]

    contact = crm_contacts.get(from_email)
    if contact:
        lines.append("")
        lines.append("CONTACT (from CRM):")
        lines.append(
            f"  Company: {contact.get('company', '')} | "
            f"Role: {contact.get('role', '')} | Status: {contact.get('status', '')}"
        )
        if contact.get("summary"):
            lines.append(f"  History: {contact['summary']}")

    matched_projects = _find_projects_for_email(from_email, subject, preview, all_projects)
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


def _extract_batch(
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
        print(f"[CommitmentsExtract] Batch extraction failed: {e}")
        return []


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress=None,
) -> dict:
    """
    Extract commitments (mine + theirs) from screened inbox.
    Returns standard section result dict.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    settings = settings or {}
    display_name = settings.get("display_name", "the executive")
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    own_email = (settings.get("report_email") or settings.get("username") or "").lower()

    # ── 1. Skill + user instruction ───────────────────────
    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""
    instruction_path = data_dir / "instructions" / "commitments_extract.md"
    user_instruction = instruction_path.read_text().strip() if instruction_path.exists() else ""

    # ── 2. Load CRM + Projects ────────────────────────────
    log("Loading CRM and Projects DB...")
    crm_data = load_crm(data_dir)
    crm_contacts = crm_data.get("contacts", {})
    ignored_emails: set = {
        email for email, c in crm_contacts.items()
        if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore"
    }

    projects_db = load_projects(data_dir)
    all_projects = list(projects_db.get("projects", {}).values())

    # ── 3. Load cache + determine fetch range ─────────────
    cache = load_cache(data_dir)
    prune_cache(cache)
    last_processed = get_last_processed(cache)
    force_refresh = settings.get("commitment_force_refresh", False)

    if last_processed and not force_refresh:
        log(f"Incremental fetch: new emails since {last_processed[:19]}")
        try:
            raw_inbox = graph.get_messages_since_datetime(last_processed, max_results=100)
        except Exception as e:
            log(f"Incremental fetch failed: {e}")
            raw_inbox = []
    else:
        if force_refresh:
            log("Force refresh: clearing cache, fetching 21 days...")
            cache = {}
        else:
            log("First run: fetching inbox (last 21 days)...")
        try:
            raw_inbox = graph.get_messages_since(days=21, max_results=300)
        except Exception as e:
            log(f"Inbox fetch failed: {e}")
            raw_inbox = []

    # ── 4. Screen + extract only NEW emails ───────────────
    # Skip emails already in cache
    cached_ids = set(cache.get("emails", {}).keys())
    new_inbox = [m for m in raw_inbox if m.get("id") not in cached_ids]
    log(f"{len(new_inbox)} new emails to process ({len(raw_inbox) - len(new_inbox)} already cached)")

    if new_inbox:
        log(f"Screening {len(new_inbox)} new emails...")
        screened = screen_emails(
            messages=new_inbox,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=load_profile_context(data_dir),
            display_name=display_name,
            progress=log,
        )
        visible_new = [m for m in screened if not m.get("screened_out")]

        if own_email:
            visible_new = [m for m in visible_new if _get_sender(m)[0] != own_email]

        log(f"{len(visible_new)} visible new emails to analyze for commitments")

        # Build context blocks for new emails only
        indexed: list[tuple[int, dict, str]] = []
        for i, msg in enumerate(visible_new, start=1):
            ctx = _build_email_context_block(i, msg, crm_contacts, all_projects)
            indexed.append((i, msg, ctx))

        # AI batch extraction on new emails
        index_map: dict[int, dict] = {i: msg for i, msg, _ in indexed}
        batches = [indexed[j:j + _BATCH_SIZE] for j in range(0, len(indexed), _BATCH_SIZE)]
        for b_num, batch in enumerate(batches, 1):
            log(f"Extracting commitments from batch {b_num}/{len(batches)} ({len(batch)} emails)...")
            extracted = _extract_batch(batch, skill_text, ai, display_name, date_str, user_instruction)
            for c in extracted:
                if not isinstance(c, dict):
                    continue
                email_index = c.get("email_index")
                if email_index not in index_map:
                    continue
                msg = index_map[email_index]
                email_id = msg.get("id", "")
                received = msg.get("receivedDateTime", "")
                # Accumulate per-email, then write to cache after loop
                pending = cache.setdefault("_pending", {})
                if email_id not in pending:
                    pending[email_id] = {"received": received, "_msg": msg, "commitments": []}
                pending[email_id]["commitments"].append(c)

        # Write pending extractions into cache (with msg_meta for dedup on future runs)
        for email_id, entry in cache.pop("_pending", {}).items():
            src_msg = entry.get("_msg") or {}
            add_email_result(cache, email_id, entry["received"], entry["commitments"], msg=src_msg)

        # Also mark emails with 0 commitments as processed (so we skip them next run)
        for i, msg, _ in indexed:
            eid = msg.get("id", "")
            if eid not in cache.get("emails", {}):
                add_email_result(cache, eid, msg.get("receivedDateTime", ""), [], msg=msg)

        save_cache(data_dir, cache)

    # Clear force_refresh flag if set
    if force_refresh and settings.get("commitment_force_refresh"):
        settings["commitment_force_refresh"] = False

    # ── 5. Flatten all cached commitments ─────────────────
    # Build msg_index from all fetched emails (new + cached context is minimal;
    # we only have full msg objects for emails fetched this run)
    msg_index: dict[str, dict] = {m.get("id", ""): m for m in raw_inbox}
    all_raw = flatten_commitments(cache, msg_index)
    log(f"{len(all_raw)} raw commitments extracted before dedup")

    # ── 6. Dedup ──────────────────────────────────────────
    # Key: type + contact_email + normalized description[:50]
    # Keep the one from the most recently received email
    dedup: dict[str, dict] = {}
    for c in all_raw:
        msg = c.get("_msg") or {}
        from_email, _ = _get_sender(msg)
        ctype = c.get("type", "")
        desc = _normalize_desc(c.get("description", ""))
        key = f"{ctype}||{from_email}||{desc}"
        existing = dedup.get(key)
        received = c.get("_received") or ""
        if not existing or received > (existing.get("_received") or ""):
            dedup[key] = c

    unique_commitments = list(dedup.values())
    log(f"{len(unique_commitments)} commitments after dedup")

    # ── 7. Assemble items ─────────────────────────────────
    items = []
    for c in unique_commitments:
        msg = c.get("_msg") or {}
        from_email, from_name = _get_sender(msg)

        contact = crm_contacts.get(from_email)
        contact_summary = None
        if contact:
            contact_summary = {
                "name":         contact.get("name", from_name),
                "company":      contact.get("company", ""),
                "role":         contact.get("role", ""),
                "status":       contact.get("status", ""),
                "last_contact": contact.get("last_contact", ""),
            }

        matched_projects = _find_projects_for_email(
            from_email, msg.get("subject", ""), msg.get("bodyPreview", ""), all_projects
        )
        project_summary = None
        if matched_projects:
            p = matched_projects[0]
            project_summary = {
                "id":       p.get("id", ""),
                "name":     p.get("name", ""),
                "status":   p.get("status", ""),
                "momentum": p.get("momentum", ""),
            }

        email_id = c.get("_email_id") or msg.get("id", "")
        commitment_id = _commitment_id(
            email_id, c.get("type", ""), c.get("description", "")
        )

        items.append({
            "id":                  commitment_id,
            "type":                c.get("type", "my_commitment"),
            "description":         c.get("description", ""),
            "due_date":            c.get("due_date"),
            "due_date_confidence": c.get("due_date_confidence", "none"),
            "contact_email":       from_email,
            "contact_name":        from_name,
            "email_id":            email_id,
            "subject":             (msg.get("subject") or "(no subject)")[:200],
            "received":            c.get("_received") or msg.get("receivedDateTime", ""),
            "priority":            c.get("priority", "medium"),
            "contact":             contact_summary,
            "project":             project_summary,
        })

    # ── 8. Validator ──────────────────────────────────────
    if items:
        log(f"Validator reviewing {len(items)} commitments...")
        items = validate_output(
            items=items,
            ai=ai,
            section_id="commitments_extract",
            user_instruction=user_instruction,
            display_name=display_name,
            date_str=date_str,
        )
        log(f"{len(items)} commitments remain after validation")

    # ── 9. Sort ───────────────────────────────────────────
    # my_commitment before their_commitment, due_date asc (nulls last), priority asc
    today_str = datetime.now().strftime("%Y-%m-%d")
    priority_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {"my_commitment": 0, "their_commitment": 1}

    def sort_key(x):
        due = x.get("due_date") or "9999-99-99"
        return (
            type_order.get(x.get("type", "my_commitment"), 0),
            priority_order.get(x.get("priority", "medium"), 1),
            due,
        )

    items.sort(key=sort_key)

    # ── 10. State filtering (done / asked / snoozed) ──────
    ask_days     = int(settings.get("commitment_ask_days", 7))
    expire_hours = int(settings.get("commitment_expire_hours", 24))
    state        = load_state(data_dir)
    expired      = expire_asked(state)       # move stale asked → done
    if expired:
        log(f"{len(expired)} commitments auto-expired")

    newly_asked: list[dict] = []
    visible_items: list[dict] = []

    for item in items:
        cid = item["id"]
        if not should_show(cid, state, today_str):
            continue
        # Check if this item should trigger a check-in
        received_date = (item.get("received") or "")[:10]
        due_date      = item.get("due_date")
        days_old = 0
        if received_date:
            try:
                from datetime import date
                days_old = (date.today() - date.fromisoformat(received_date)).days
            except Exception:
                pass
        is_stale = (
            (not due_date and days_old >= ask_days) or
            (due_date and due_date < today_str)
        )
        if is_stale:
            mark_asked(data_dir, cid, expire_hours)
            newly_asked.append(item)
            # Still include in result so bot can reference by number
            item = {**item, "_asked": True}
        visible_items.append(item)

    save_state(data_dir, state)

    if newly_asked:
        log(f"Check-in triggered for {len(newly_asked)} stale commitments")

    result = {
        "id":          "commitments_extract",
        "status":      "fresh",
        "last_run":    datetime.now(timezone.utc).isoformat(),
        "items":       visible_items,
        "count":       len(visible_items),
        "empty":       len(visible_items) == 0,
        "newly_asked": [c["id"] for c in newly_asked],
    }
    _save_result(data_dir, result)

    my_count = sum(1 for x in visible_items if x["type"] == "my_commitment")
    their_count = len(visible_items) - my_count
    log(f"Commitments done — {len(visible_items)} total ({my_count} mine, {their_count} theirs)")
    return result
