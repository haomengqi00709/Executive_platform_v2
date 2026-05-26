"""
Projects DB — builds and maintains a project database from email thread history.

Extracts ongoing projects, deals, and initiatives from email conversations.
Parallel to CRM but tracks projects, not contacts.

Noise filtering:
  - Uses full screen_emails() (AI-based) because bodyPreview is available.
  - CRM uses _is_noise() (address-based) because it works from metadata only.

Storage: .data/{user_id}/projects.json — caller owns read/write.
build_projects() and refresh_projects() return dicts; callers must call save_projects().
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.screener import screen_emails
from src.modules.crm import _is_noise
from src.modules.profile import load_profile_context

_EXPENSE_SUBJECTS = re.compile(
    r"\b(receipt|invoice|payment|order confirm|subscription|billing|statement|"
    r"unsubscribe|newsletter|no-reply|noreply)\b",
    re.IGNORECASE,
)

_BATCH_SIZE = 10
_MAX_CONVERSATIONS = 80
_STALE_DAYS = 7
_INACTIVE_DAYS = 30


def load_projects(data_dir: Path) -> dict:
    """Load projects.json. Returns empty structure if file does not exist."""
    path = Path(data_dir) / "projects.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"last_scan": None, "projects": {}}


def save_projects(data_dir: Path, projects: dict) -> None:
    """Atomic write to projects.json."""
    path = Path(data_dir) / "projects.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(projects, indent=2, ensure_ascii=False))
    tmp.replace(path)


# ── Private helpers ──────────────────────────────────────

def _group_by_conversation(messages: list[dict]) -> dict[str, list[dict]]:
    """Group messages by conversationId."""
    groups: dict[str, list[dict]] = {}
    for m in messages:
        cid = m.get("conversationId") or m.get("id", "")
        groups.setdefault(cid, []).append(m)
    return groups


def _is_expense_subject(subject: str) -> bool:
    return bool(_EXPENSE_SUBJECTS.search(subject or ""))


def _filter_conversations(groups: dict[str, list[dict]]) -> list[tuple[str, list[dict]]]:
    """
    Remove noise conversations and return sorted (cid, messages) pairs.

    Keeps conversations with:
      - >= 2 messages
      - at least 1 non-noise external participant
      - subject not matching expense/transactional patterns
    """
    result = []
    for cid, msgs in groups.items():
        if len(msgs) < 2:
            continue

        subject = msgs[0].get("subject", "")
        if _is_expense_subject(subject):
            continue

        participants = set()
        for m in msgs:
            addr = (
                (m.get("from") or {})
                .get("emailAddress", {})
                .get("address", "")
                .lower()
            )
            if addr:
                participants.add(addr)

        has_real_contact = any(not _is_noise(addr) for addr in participants)
        if not has_real_contact:
            continue

        last_activity = max(
            (m.get("receivedDateTime") or m.get("sentDateTime") or "")
            for m in msgs
        )
        result.append((cid, msgs, last_activity))

    result.sort(key=lambda x: x[2], reverse=True)
    return [(cid, msgs) for cid, msgs, _ in result[:_MAX_CONVERSATIONS]]


def _build_conversation_text(cid: str, msgs: list[dict]) -> str:
    """Format a conversation cluster for the AI prompt."""
    lines = [f"CONVERSATION_ID: {cid}"]
    for m in msgs[:6]:
        subject = (m.get("subject") or "(no subject)")[:100]
        from_addr = (
            (m.get("from") or {}).get("emailAddress", {}).get("address", "")
        )
        preview = (m.get("bodyPreview") or "")[:200]
        date = (m.get("receivedDateTime") or m.get("sentDateTime") or "")[:10]
        lines.append(f"  [{date}] {from_addr}: {subject} | {preview}")
    return "\n".join(lines)


def _extract_projects_from_batch(
    batch: list[tuple[str, list[dict]]],
    ai: AIClient,
    display_name: str,
    today_str: str,
) -> list[dict]:
    """
    Send a batch of conversations to Gemini and extract project entries.
    Returns a list of project dicts.
    """
    conv_blocks = "\n\n".join(
        _build_conversation_text(cid, msgs) for cid, msgs in batch
    )

    prompt = f"""You are analyzing email conversations to identify ongoing business projects, deals, or initiatives for {display_name}. Today is {today_str}.

Below are email conversation clusters (grouped by thread). For each cluster that represents a real project or business initiative:
- Assign a short descriptive name (e.g., "Acme Corp — Q3 Deal")
- Generate a kebab-case id (e.g., "acme-q3-deal")
- Classify category: client_deal / internal / vendor / partnership / other
- Assess status: one of these exact values:
    * early_stage — project just started (kick-off, scoping, first few exchanges)
    * ongoing — project is in normal active execution, no major issues
    * needs_attention — project has problems: stuck, customer cooling, momentum declining, risk surfacing
    * paused — intentionally on hold, waiting on an external decision/dependency (not the same as problems — paused is OK, needs_attention is concerning)
    * completed — project is done / delivered / archived
- Assess momentum: accelerating / steady / slowing / stalled
- Write a 1-2 sentence summary of the current state
- Identify the most recent activity date (YYYY-MM-DD)
- Extract participant email addresses
- Note the next action if clear from the emails
- Extract deadline if explicitly mentioned (YYYY-MM-DD), else null
- List 3-5 key topics
- Count total emails in the cluster
- List all conversation_ids that belong to this project

IMPORTANT:
- If multiple clusters belong to the same project, merge them (list all conversation_ids)
- Skip clusters that are purely transactional (receipts, calendar invites), newsletters, one-off admin emails, or internal notifications with no substantive back-and-forth
- Return ONLY a JSON array of project objects with these exact fields:
  id, name, category, status, momentum, summary, last_activity, deadline, participants, next_action, key_topics, thread_count, conversation_ids

CONVERSATIONS:
{conv_blocks}

Return only the JSON array, no explanation."""

    try:
        raw = ai.generate(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        projects = json.loads(raw)
        if not isinstance(projects, list):
            return []
        return projects
    except Exception as e:
        print(f"[Projects] Batch extraction failed: {e}")
        return []


def _merge_projects(existing: dict, new_projects: list[dict]) -> dict:
    """
    Merge newly extracted projects into the existing projects dict.
    Deduplicates by id; merges conversation_ids on collision.
    """
    for p in new_projects:
        pid = p.get("id", "")
        if not pid:
            continue
        p.setdefault("ignore", False)
        p.setdefault("updated_at", datetime.now().strftime("%Y-%m-%d"))

        if pid in existing:
            # Merge conversation_ids, update counts and recency
            old = existing[pid]
            merged_convs = list(set(old.get("conversation_ids", []) + p.get("conversation_ids", [])))
            p["conversation_ids"] = merged_convs
            p["thread_count"] = max(old.get("thread_count", 0), p.get("thread_count", 0))
            p["ignore"] = old.get("ignore", False)
        existing[pid] = p

    return existing


# ── Public API ────────────────────────────────────────────

def build_projects(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress_cb=None,
    months: int = 6,
) -> dict:
    """
    Full project extraction from the last `months` of email.
    Returns a new projects dict; caller must call save_projects().
    """
    def log(msg: str):
        if progress_cb:
            progress_cb(msg)
        print(f"[Projects] {msg}")

    data_dir = Path(data_dir)
    settings = settings or {}
    display_name = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir)
    today_str = datetime.now().strftime("%Y-%m-%d")
    days_window = max(1, int(months)) * 30

    # ── Phase 1: Fetch inbox messages (with bodyPreview) ──
    log(f"Fetching inbox messages ({months} months)...")
    try:
        inbox_msgs = graph.get_messages_since(days=days_window, max_results=500)
    except Exception as e:
        log(f"Inbox fetch failed: {e}")
        inbox_msgs = []

    # ── Screen inbox through AI screener ─────────────────
    ignored_emails: set = set()
    try:
        from src.modules.crm import load_crm
        crm_data = load_crm(data_dir)
        ignored_emails = {
            email for email, c in crm_data.get("contacts", {}).items()
            if c.get("ignore") or c.get("archived")
        }
    except Exception:
        pass

    if inbox_msgs:
        log(f"Screening {len(inbox_msgs)} inbox messages...")
        screened = screen_emails(
            messages=inbox_msgs,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=business_context,
            display_name=display_name,
        )
        visible_inbox = [m for m in screened if not m.get("screened_out")]
    else:
        visible_inbox = []

    # ── Fetch sent messages (no screening — these are our own) ──
    log("Fetching sent messages (6 months)...")
    try:
        sent_msgs = graph.get_sent_messages_since(days=180, max_results=300)
    except Exception as e:
        log(f"Sent fetch failed: {e}")
        sent_msgs = []

    all_messages = visible_inbox + sent_msgs
    log(f"Total messages after screening: {len(all_messages)} ({len(visible_inbox)} inbox + {len(sent_msgs)} sent)")

    # ── Phase 2: Group by conversationId ─────────────────
    groups = _group_by_conversation(all_messages)
    log(f"Found {len(groups)} unique conversations")

    # ── Phase 3: Filter noise conversations ──────────────
    filtered = _filter_conversations(groups)
    log(f"After noise filtering: {len(filtered)} conversations (max {_MAX_CONVERSATIONS})")

    # ── Phase 4: AI batch extraction ─────────────────────
    all_projects_raw: list[dict] = []
    batches = [filtered[i:i + _BATCH_SIZE] for i in range(0, len(filtered), _BATCH_SIZE)]
    for i, batch in enumerate(batches, 1):
        log(f"Extracting projects from batch {i}/{len(batches)} ({len(batch)} conversations)...")
        extracted = _extract_projects_from_batch(batch, ai, display_name, today_str)
        log(f"  → {len(extracted)} project(s) found")
        all_projects_raw.extend(extracted)

    # ── Phase 5: Deduplicate and merge ───────────────────
    projects_dict: dict = {}
    projects_dict = _merge_projects(projects_dict, all_projects_raw)
    log(f"Total projects after dedup: {len(projects_dict)}")

    return {
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "projects": projects_dict,
    }


def refresh_projects(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    progress_cb=None,
) -> dict:
    """
    Incremental update since last_scan.
    Returns updated projects dict; caller must call save_projects().
    """
    def log(msg: str):
        if progress_cb:
            progress_cb(msg)
        print(f"[Projects] {msg}")

    data_dir = Path(data_dir)
    settings = settings or {}
    display_name = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir)
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    existing = load_projects(data_dir)
    last_scan_str = existing.get("last_scan")

    # Determine scan window (min 2 days, max 30 days)
    if last_scan_str:
        try:
            last_scan_dt = datetime.fromisoformat(last_scan_str.replace("Z", "+00:00"))
            delta = now - last_scan_dt
            days_back = max(2, min(int(delta.total_seconds() / 86400) + 1, 30))
        except Exception:
            days_back = 7
    else:
        days_back = 7

    log(f"Scanning last {days_back} days for new email activity...")

    # ── Fetch recent inbox ────────────────────────────────
    try:
        inbox_msgs = graph.get_messages_since(days=days_back, max_results=200)
    except Exception as e:
        log(f"Inbox fetch failed: {e}")
        inbox_msgs = []

    ignored_emails: set = set()
    try:
        from src.modules.crm import load_crm
        crm_data = load_crm(data_dir)
        ignored_emails = {
            email for email, c in crm_data.get("contacts", {}).items()
            if c.get("ignore") or c.get("archived")
        }
    except Exception:
        pass

    if inbox_msgs:
        log(f"Screening {len(inbox_msgs)} inbox messages...")
        screened = screen_emails(
            messages=inbox_msgs,
            ai=ai,
            ignored_emails=ignored_emails,
            business_context=business_context,
            display_name=display_name,
        )
        visible_inbox = [m for m in screened if not m.get("screened_out")]
    else:
        visible_inbox = []

    try:
        sent_msgs = graph.get_sent_messages_since(days=days_back, max_results=100)
    except Exception as e:
        log(f"Sent fetch failed: {e}")
        sent_msgs = []

    all_messages = visible_inbox + sent_msgs
    if not all_messages:
        log("No new messages found — updating last_scan only")
        existing["last_scan"] = now.isoformat()
        return existing

    # ── Group and filter ──────────────────────────────────
    groups = _group_by_conversation(all_messages)
    filtered = _filter_conversations(groups)
    log(f"Found {len(filtered)} relevant conversations in new messages")

    # Build lookup: conversationId → project_id
    conv_to_project: dict[str, str] = {}
    for pid, proj in existing.get("projects", {}).items():
        for cid in proj.get("conversation_ids", []):
            conv_to_project[cid] = pid

    stale_threshold = (now - timedelta(days=_STALE_DAYS)).strftime("%Y-%m-%d")
    inactive_threshold = (now - timedelta(days=_INACTIVE_DAYS)).strftime("%Y-%m-%d")

    matched_pids: set[str] = set()
    unmatched_convs: list[tuple[str, list[dict]]] = []

    for cid, msgs in filtered:
        if cid in conv_to_project:
            pid = conv_to_project[cid]
            matched_pids.add(pid)
            proj = existing["projects"][pid]

            # Update last_activity and thread_count
            last_activity = max(
                (m.get("receivedDateTime") or m.get("sentDateTime") or "")
                for m in msgs
            )[:10]
            if last_activity > proj.get("last_activity", ""):
                proj["last_activity"] = last_activity

            proj["thread_count"] = proj.get("thread_count", 0) + len(msgs)

            # Re-enrich if stale
            if proj.get("updated_at", "9999") < stale_threshold:
                log(f"Re-enriching stale project: {proj.get('name', pid)}")
                batch_result = _extract_projects_from_batch([(cid, msgs)], ai, display_name, today_str)
                if batch_result:
                    refreshed = batch_result[0]
                    for field in ("status", "momentum", "summary", "next_action"):
                        if field in refreshed:
                            proj[field] = refreshed[field]
                    proj["updated_at"] = today_str
        else:
            unmatched_convs.append((cid, msgs))

    # ── Find brand new projects ───────────────────────────
    if unmatched_convs:
        log(f"Checking {len(unmatched_convs)} new conversations for new projects...")
        new_projects_raw: list[dict] = []
        batches = [unmatched_convs[i:i + _BATCH_SIZE] for i in range(0, len(unmatched_convs), _BATCH_SIZE)]
        for i, batch in enumerate(batches, 1):
            extracted = _extract_projects_from_batch(batch, ai, display_name, today_str)
            new_projects_raw.extend(extracted)
        if new_projects_raw:
            log(f"Found {len(new_projects_raw)} new project(s)")
            existing["projects"] = _merge_projects(existing.get("projects", {}), new_projects_raw)

    # ── Mark completed projects ───────────────────────────
    for pid, proj in list(existing.get("projects", {}).items()):
        if proj.get("status") == "completed":
            continue
        if proj.get("ignore") or proj.get("archived"):
            continue
        last_act = proj.get("last_activity", "")
        if last_act and last_act < inactive_threshold:
            log(f"Marking {proj.get('name', pid)} as completed (no activity in 30 days)")
            proj["status"] = "completed"
            proj["updated_at"] = today_str

    existing["last_scan"] = now.isoformat()
    log(f"Refresh done — {len(existing.get('projects', {}))} total projects")
    return existing
