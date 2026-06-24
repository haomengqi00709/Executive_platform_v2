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
    """Persist the projects DB. Routed through the SQLite store (per-project rows in one transaction
    — no whole-file corruption race that the old direct projects.json write had); projects.json is
    regenerated as a synced projection so every reader stays unchanged. Edit-preservation for the AI
    rebuild is kept UPSTREAM in refresh_projects / _merge_projects (parity with the prior behaviour).
    Deferred import avoids any import cycle."""
    from src.modules import projects_store
    projects_store.replace_from_dict(data_dir, projects)


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


# ── Entity-centric helpers (anchored broad re-scan) ──────
#
# A project is an entity (people + topic) that spans MANY email threads — not a
# single conversationId. The refresh re-derives each project's state from a broad
# recent scan of all mail involving its people, so a new thread about an existing
# project updates that project instead of spawning a duplicate or freezing it.

_REFRESH_WINDOW_DAYS = 45   # broad re-scan window for refresh()
_DORMANT_DAYS = 45          # no cross-thread activity in this window → dormant flag


def _owner_addresses(data_dir: Path, settings: dict) -> set[str]:
    """The owner's own addresses — excluded from a project's fingerprint. The owner
    is a participant in every project, so matching on them would match everything."""
    addrs: set[str] = set()
    rep = (settings or {}).get("report_email")
    if rep:
        addrs.add(rep.lower())
    # OAuth login identity is the most reliable owner address.
    try:
        uid = Path(data_dir).name
        sess = Path(data_dir).parent / "_sessions" / f"{uid}.json"
        if sess.exists():
            u = json.loads(sess.read_text()).get("username")
            if u:
                addrs.add(u.lower())
    except Exception:
        pass
    return addrs


def _msg_external_addrs(m: dict, owner_addrs: set[str]) -> set[str]:
    """External (non-owner, non-noise) addresses on a message — from + to."""
    cands = [((m.get("from") or {}).get("emailAddress", {}).get("address", "") or "").lower()]
    for r in (m.get("toRecipients") or []):
        cands.append(((r.get("emailAddress") or {}).get("address") or "").lower())
    return {a for a in cands if a and a not in owner_addrs and not _is_noise(a)}


def _project_participants(proj: dict, owner_addrs: set[str]) -> set[str]:
    return {
        p.lower() for p in (proj.get("participants") or [])
        if p and p.lower() not in owner_addrs and not _is_noise(p.lower())
    }


def _msg_date(m: dict) -> str:
    return (m.get("receivedDateTime") or m.get("sentDateTime") or "")[:10]


def _reassess_project(proj: dict, msgs: list[dict], ai: AIClient,
                      display_name: str, today_str: str) -> dict | None:
    """Given an EXISTING project and CANDIDATE emails (matched by shared participant —
    but the same people also email about OTHER topics), have the AI (1) pick which
    threads are ACTUALLY about this project, then (2) re-assess its state from only
    those. This is what stops a high-frequency contact's unrelated mail from being
    lumped into one project. Returns a dict with relevant_conversation_ids + the
    AI-derived fields, or None."""
    by_cid: dict[str, list[dict]] = {}
    for m in msgs:
        by_cid.setdefault(m.get("conversationId") or m.get("id", ""), []).append(m)

    labels: dict[str, str] = {}   # "T1" -> conversationId
    blocks: list[str] = []
    for i, (cid, ms) in enumerate(by_cid.items(), 1):
        lab = f"T{i}"
        labels[lab] = cid
        ms_sorted = sorted(ms, key=_msg_date)
        subj = (ms_sorted[-1].get("subject") or "(no subject)")[:90]
        prev = (ms_sorted[-1].get("bodyPreview") or "")[:150]
        blocks.append(f"  {lab} [{_msg_date(ms_sorted[-1])}] {subj} | {prev}")

    prompt = f"""You are maintaining an EXISTING project for {display_name}. Today is {today_str}.
Do NOT rename or split it — its identity is fixed.

PROJECT:
  name: {proj.get('name', '')}
  current summary: {proj.get('summary', '')}

Below are recent email THREADS involving this project's people. IMPORTANT: these
people also discuss OTHER topics/projects — only some threads are about THIS project.
Exclude anything that is not about this specific project.

THREADS:
{chr(10).join(blocks)}

Return ONLY a JSON object:
  "relevant_threads": [thread labels that are ACTUALLY about THIS project, e.g. ["T1","T3"]; [] if none]
  "status": early_stage | ongoing | needs_attention | paused | completed
  "momentum": accelerating | steady | slowing | stalled
  "summary": 1-2 sentence current state, based ONLY on the relevant threads
  "next_action": next concrete action if clear, else ""
Return only the JSON object, no explanation."""
    try:
        raw = ai.generate(prompt).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        out = json.loads(raw)
        if not isinstance(out, dict):
            return None
        rel = out.get("relevant_threads") or []
        out["relevant_conversation_ids"] = [labels[l] for l in rel if l in labels]
        return out
    except Exception as e:
        print(f"[Projects] Re-assess failed for {proj.get('name', '?')}: {e}")
        return None


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

    # Anchored broad re-scan: always look back a FIXED window so a project's recent
    # activity across ALL threads is visible — not just new mail since last_scan.
    days_back = _REFRESH_WINDOW_DAYS
    log(f"Broad re-scan: last {days_back} days of mail...")

    # ── Fetch recent inbox ────────────────────────────────
    try:
        inbox_msgs = graph.get_messages_since(days=days_back, max_results=500)
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

    # ── Entity-centric re-assessment (anchored broad re-scan) ──
    owner_addrs = _owner_addresses(data_dir, settings)
    projects = existing.get("projects", {})

    # 1) Re-assess each active project from ALL recent mail involving its people —
    #    across every thread, not just its known conversationIds. This is what
    #    fixes "frozen" projects whose new activity lives in a fresh thread.
    claimed_ids: set[str] = set()
    for pid, proj in projects.items():
        if proj.get("ignore") or proj.get("archived"):
            continue
        parts = _project_participants(proj, owner_addrs)
        if not parts:
            continue
        # Candidates = mail sharing a participant. The same people email about other
        # things, so the AI then keeps only threads ACTUALLY about this project.
        cand = [m for m in all_messages if _msg_external_addrs(m, owner_addrs) & parts]
        if not cand:
            continue
        result = _reassess_project(proj, cand, ai, display_name, today_str)
        if not result:
            continue
        rel_cids = set(result.get("relevant_conversation_ids", []))
        rel_msgs = [m for m in cand if (m.get("conversationId") or m.get("id", "")) in rel_cids]
        if not rel_msgs:
            log(f"Re-assessed '{proj.get('name', pid)}': 0/{len(cand)} candidate threads relevant — skipped")
            continue
        for m in rel_msgs:
            claimed_ids.add(m.get("id", ""))
        latest = max(_msg_date(m) for m in rel_msgs)
        if latest > proj.get("last_activity", ""):
            proj["last_activity"] = latest
        proj["conversation_ids"] = sorted(set(proj.get("conversation_ids", [])) | rel_cids)
        proj["thread_count"] = len(proj["conversation_ids"])
        for f in ("status", "momentum", "summary", "next_action"):
            if result.get(f) not in (None, ""):
                proj[f] = result[f]
        proj["updated_at"] = today_str
        log(f"Re-assessed '{proj.get('name', pid)}': "
            f"{len(rel_msgs)}/{len(cand)} msgs relevant → {proj.get('status')}")

    # 2) Unclaimed mail → candidate NEW projects. Reconcile against existing first
    #    (≥2 shared external participants → fold in, don't create a duplicate).
    unclaimed = [m for m in all_messages if m.get("id", "") not in claimed_ids]
    filtered = _filter_conversations(_group_by_conversation(unclaimed))
    if filtered:
        log(f"Checking {len(filtered)} unclaimed conversation(s) for new projects...")
        new_raw: list[dict] = []
        for i in range(0, len(filtered), _BATCH_SIZE):
            new_raw.extend(_extract_projects_from_batch(
                filtered[i:i + _BATCH_SIZE], ai, display_name, today_str))
        truly_new: list[dict] = []
        for np in new_raw:
            np_parts = {p.lower() for p in (np.get("participants") or [])
                        if p and p.lower() not in owner_addrs and not _is_noise(p.lower())}
            best_pid, best_ov = None, 0
            for pid, proj in projects.items():
                ov = len(np_parts & _project_participants(proj, owner_addrs))
                if ov > best_ov and ov >= 2:
                    best_pid, best_ov = pid, ov
            if best_pid:  # same people as an existing project → fold in, no duplicate
                ex = projects[best_pid]
                ex["conversation_ids"] = sorted(
                    set(ex.get("conversation_ids", [])) | set(np.get("conversation_ids", [])))
                ex["thread_count"] = len(ex["conversation_ids"])
                log(f"Folded new cluster into existing '{ex.get('name', best_pid)}' (shared {best_ov})")
            else:
                truly_new.append(np)
        if truly_new:
            log(f"Found {len(truly_new)} genuinely new project(s)")
            projects = _merge_projects(projects, truly_new)

    # 3) Lifecycle: flag dormant by BROAD-scan inactivity. We do NOT auto-complete
    #    on inactivity anymore (that wrongly buried active-but-frozen projects);
    #    'completed' is now decided only by the AI re-assessment or the user.
    dormant_threshold = (now - timedelta(days=_DORMANT_DAYS)).strftime("%Y-%m-%d")
    for pid, proj in projects.items():
        if proj.get("archived"):
            continue
        la = (proj.get("last_activity") or "")
        proj["dormant"] = bool(la and la < dormant_threshold and proj.get("status") != "completed")

    existing["projects"] = projects
    existing["last_scan"] = now.isoformat()
    log(f"Refresh done — {len(projects)} projects")
    return existing
