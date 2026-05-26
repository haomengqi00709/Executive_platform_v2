"""
CRM — builds and maintains a contact database from email history.

Scan phases:
  1. Fetch inbox + sent metadata (no body) for last N months
  2. Group by contact email → thread_count, last_contact
  3. Filter: min 2 threads, top 200 by recency
  4. AI enrichment per contact: company / role / status / summary / writing_style

Storage: .data/{user_id}/crm.json — caller owns read/write (use load_crm / save_crm).
build_crm() returns a dict and never touches the filesystem.
"""
import html as _html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient

_NOISE_PATTERNS = [
    "noreply", "no-reply", "postmaster", "mailer-daemon",
    "notifications@", "alerts@", "donotreply", "bounce",
    "dse@docusign", "feedback@slack", "notify@notion",
    "receipts@stripe", "noreply@linkedin", "noreply@calendly",
    "microsoftexchange", "support@", "info@", "admin@",
]


def _is_noise(addr: str) -> bool:
    addr = addr.lower()
    return any(p in addr for p in _NOISE_PATTERNS)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _guess_company(addr: str) -> str:
    domain = addr.split("@")[-1] if "@" in addr else ""
    if not domain:
        return ""
    return domain.split(".")[0].title()


def _enrich_contact(
    addr: str,
    base: dict,
    graph: GraphClient,
    ai: AIClient,
    market_segments_content: str = "",
    sent_snippets: list[str] | None = None,
) -> dict:
    """Fetch last 5 emails from contact, AI-generate enrichment fields."""
    try:
        msgs = graph.get_messages(
            top=5,
            filter=f"from/emailAddress/address eq '{addr}'",
            orderby=None,
        )
    except Exception:
        msgs = []

    fallback = {
        **base,
        "company":       _guess_company(addr),
        "role":          "",
        "phone":         "",
        "linkedin":      "",
        "status":        "other",
        "summary":       "",
        "writing_style": "",
        "updated_at":    datetime.now().strftime("%Y-%m-%d"),
    }

    if not msgs:
        return fallback

    snippets = "\n\n---\n\n".join(
        f"[{m.get('receivedDateTime', '')[:10]}] {m.get('subject', '')}\n"
        f"{_strip_html(m.get('body', {}).get('content', '') or m.get('bodyPreview', ''))[:1200]}"
        for m in msgs
    )

    seg_block = (
        f"\n\nUse this market segmentation guide to determine the correct status:\n"
        f"{market_segments_content[:4000]}"
    ) if market_segments_content else ""

    sent_block = ""
    if sent_snippets:
        sent_block = (
            "\n\nEMAILS THE USER SENT TO THIS CONTACT (most recent first):\n"
            + "\n---\n".join(sent_snippets)
        )

    prompt = (
        f"Analyze these emails from {base.get('name') or addr} and extract structured info.\n\n"
        f"EMAILS RECEIVED FROM THIS CONTACT:\n{snippets}{sent_block}{seg_block}\n\n"
        f"Pay close attention to email signatures for name, title, phone, and LinkedIn.\n\n"
        f"Reply ONLY with a JSON object with exactly these keys:\n"
        f"  company: string (from signature or email domain)\n"
        f"  role: string (job title from signature, or empty string)\n"
        f"  phone: string (phone from signature, or empty string)\n"
        f"  linkedin: string (LinkedIn URL from signature, or empty string)\n"
        f"  status: one of: client, prospect, partner, investor, vendor, internal, other\n"
        f"    (investor = stakeholders / capital providers / board members; "
        f"internal = your own company's employees & contractors)\n"
        f"  summary: string (1-2 sentences about the relationship and recent topics)\n"
        f"  writing_style: string (from SENT emails — concrete details: "
        f"(1) exact greeting e.g. 'Hi John,'; "
        f"(2) exact sign-off e.g. 'Cheers, Daniel'; "
        f"(3) 3-5 verbatim characteristic phrases; "
        f"(4) frequently used words; "
        f"(5) tone: formal/casual, direct/diplomatic, brief/detailed. "
        f"Empty string if no sent emails.)\n\n"
        f"JSON only, no explanation:"
    )

    try:
        raw = ai.generate(prompt).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return {
                **base,
                "company":       parsed.get("company") or _guess_company(addr),
                "role":          parsed.get("role", ""),
                "phone":         parsed.get("phone", ""),
                "linkedin":      parsed.get("linkedin", ""),
                "status":        parsed.get("status", "other"),
                "summary":       parsed.get("summary", ""),
                "writing_style": parsed.get("writing_style", ""),
                "updated_at":    datetime.now().strftime("%Y-%m-%d"),
            }
    except Exception:
        pass

    return fallback


# ── Public API ────────────────────────────────────────────


def load_crm(data_dir: Path) -> dict:
    """Load crm.json. Returns empty structure if file doesn't exist."""
    f = Path(data_dir) / "crm.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {"last_scan": None, "months_scanned": 0, "contacts": {}}


def save_crm(data_dir: Path, crm: dict) -> None:
    """Atomically write crm.json."""
    f = Path(data_dir) / "crm.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(crm, indent=2, ensure_ascii=False))
    tmp.replace(f)


def update_contact(data_dir: Path, email: str, field: str, value) -> dict:
    """Update a single field on a CRM contact. Creates the contact entry if it doesn't exist.
    'notes' field appends with timestamp instead of overwriting."""
    from datetime import datetime as _dt
    crm = load_crm(data_dir)
    contacts = crm.setdefault("contacts", {})
    contact = dict(contacts.get(email.lower(), {}))
    if field == "notes":
        existing = contact.get("notes", "")
        stamp = _dt.now().strftime("%Y-%m-%d")
        contact["notes"] = f"{existing}\n[{stamp}] {value}".strip()
    else:
        contact[field] = value
    contacts[email.lower()] = contact
    save_crm(data_dir, crm)
    return contact


def add_contacts_bulk(data_dir: Path, raw_contacts: list, source: str,
                      tags: list | None = None) -> dict:
    """Add a batch of contacts to CRM.
    Returns {"added": N, "updated": M, "skipped_no_email": K, "by_email": {email: "added"|"updated"|...}}.

    - Skips entries without a valid email.
    - For existing contacts: merges notes (appended with date stamp), unions tags,
      preserves manually-set fields (priority/ignore/writing_style).
    - For new contacts: writes name/email/company/role/phone/linkedin/notes/source/tags/added_at.
    """
    crm = load_crm(data_dir)
    contacts = crm.setdefault("contacts", {})
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now().strftime("%Y-%m-%d")
    tags = tags or []

    result = {"added": 0, "updated": 0, "skipped_no_email": 0, "by_email": {}}

    for raw in raw_contacts:
        email = (raw.get("email") or "").strip().lower()
        if not email or "@" not in email:
            result["skipped_no_email"] += 1
            continue

        existing = contacts.get(email)
        if existing:
            # Merge: union tags, append notes, fill in any missing fields
            old_tags = list(existing.get("tags") or [])
            new_tags = list(set(old_tags + tags))
            existing["tags"] = new_tags
            new_note = (raw.get("notes") or "").strip()
            if new_note:
                prior = existing.get("notes", "")
                existing["notes"] = f"{prior}\n[{today}] {new_note}".strip() if prior else f"[{today}] {new_note}"
            for f in ("name", "company", "role", "phone", "linkedin"):
                if raw.get(f) and not existing.get(f):
                    existing[f] = raw[f]
            existing.setdefault("source", existing.get("source") or source)
            existing["updated_at"] = today
            result["updated"] += 1
            result["by_email"][email] = "updated"
        else:
            note = (raw.get("notes") or "").strip()
            contacts[email] = {
                "email":       email,
                "name":        (raw.get("name") or "").strip(),
                "company":     (raw.get("company") or "").strip(),
                "role":        (raw.get("role") or "").strip(),
                "phone":       (raw.get("phone") or "").strip(),
                "linkedin":    (raw.get("linkedin") or "").strip(),
                "notes":       f"[{today}] {note}" if note else "",
                "source":      source,
                "tags":        list(tags),
                "added_at":    now_iso,
                "updated_at":  today,
                "status":      "other",
                "thread_count": 0,
            }
            result["added"] += 1
            result["by_email"][email] = "added"

    save_crm(data_dir, crm)
    return result


def tag_contacts_added_since(data_dir: Path, tag: str, hours: int) -> int:
    """Add `tag` to every contact whose added_at is within the last `hours` hours.
    Returns the number of contacts tagged."""
    crm = load_crm(data_dir)
    contacts = crm.get("contacts", {})
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    n = 0
    for c in contacts.values():
        added_at = c.get("added_at", "")
        if not added_at:
            continue
        try:
            dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff:
            continue
        tags = list(c.get("tags") or [])
        if tag not in tags:
            tags.append(tag)
            c["tags"] = tags
            n += 1
    save_crm(data_dir, crm)
    return n


def find_contacts_by_tag(data_dir: Path, tag: str) -> list:
    """Return list of contact dicts matching the given tag (case-insensitive substring match)."""
    crm = load_crm(data_dir)
    tag_lower = tag.lower()
    return [
        c for c in crm.get("contacts", {}).values()
        if any(tag_lower in t.lower() for t in (c.get("tags") or []))
    ]


def find_contacts_added_since(data_dir: Path, hours: int) -> list:
    """Return list of contact dicts added in the last `hours` hours."""
    crm = load_crm(data_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for c in crm.get("contacts", {}).values():
        added_at = c.get("added_at", "")
        if not added_at:
            continue
        try:
            dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt >= cutoff:
            out.append(c)
    return out


def build_crm(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    market_segments_content: str = "",
    months: int = 6,
    progress_cb=None,
) -> dict:
    """
    Full CRM build from email history.

    Returns {"last_scan": ISO-8601, "months_scanned": int, "contacts": {email: {...}}}.
    Does NOT write to disk — caller must call save_crm().
    Preserves manually-set fields (priority, status override) from existing crm.json.
    """
    def log(msg: str):
        print(f"[CRM] {msg}")
        if progress_cb:
            progress_cb(msg)

    existing = load_crm(data_dir)
    old_contacts: dict = existing.get("contacts", {})

    days = months * 30

    # ── Phase 1: inbox metadata ───────────────────────────
    log(f"Scanning inbox — last {months} months…")
    try:
        inbox = graph.get_inbox_metadata_since(days=days, max_results=2000)
    except Exception as e:
        log(f"Inbox scan failed: {e}")
        inbox = []
    log(f"  {len(inbox)} inbox messages")

    # ── Phase 2: sent metadata ────────────────────────────
    log("Scanning sent folder…")
    try:
        sent = graph.get_sent_messages_since(days=days, max_results=2000)
    except Exception as e:
        log(f"Sent scan failed: {e}")
        sent = []
    log(f"  {len(sent)} sent messages")

    # ── Phase 3: get owner email for self-filtering ───────
    try:
        me = graph.get_me()
        owner_lower = (me.get("mail") or me.get("userPrincipalName") or "").lower()
    except Exception:
        owner_lower = ""

    # ── Phase 4: group contacts ───────────────────────────
    contacts: dict = {}

    for msg in inbox:
        ea   = (msg.get("from") or {}).get("emailAddress") or {}
        addr = ea.get("address", "").lower()
        name = ea.get("name", "")
        date = (msg.get("receivedDateTime") or "")[:10]
        if not addr or addr == owner_lower or _is_noise(addr):
            continue
        if addr not in contacts:
            contacts[addr] = {"email": addr, "name": name, "thread_count": 0, "last_contact": date}
        contacts[addr]["thread_count"] += 1
        if date > contacts[addr]["last_contact"]:
            contacts[addr]["last_contact"] = date
        if not contacts[addr]["name"] and name:
            contacts[addr]["name"] = name

    sent_by_recipient: dict = {}
    for msg in sent:
        for r in (msg.get("toRecipients") or []):
            ea   = (r.get("emailAddress") or {})
            addr = ea.get("address", "").lower()
            name = ea.get("name", "")
            date = (msg.get("sentDateTime") or "")[:10]
            if not addr or addr == owner_lower or _is_noise(addr):
                continue
            if addr not in contacts:
                contacts[addr] = {"email": addr, "name": name, "thread_count": 0, "last_contact": date}
            contacts[addr]["thread_count"] += 1
            if date > contacts[addr]["last_contact"]:
                contacts[addr]["last_contact"] = date
            if not contacts[addr]["name"] and name:
                contacts[addr]["name"] = name
            preview = msg.get("bodyPreview", "")
            if preview:
                sent_by_recipient.setdefault(addr, []).append(
                    f"[{date}] {msg.get('subject', '')}\n{preview[:500]}"
                )

    log(f"{len(contacts)} unique contacts found")

    # ── Phase 5: filter and rank ──────────────────────────
    candidates = [c for c in contacts.values() if c["thread_count"] >= 2]
    candidates.sort(key=lambda x: x["last_contact"], reverse=True)
    candidates = candidates[:200]
    log(f"{len(candidates)} contacts after filtering (min 2 threads, top 200 by recency)")

    # ── Phase 6: AI enrich ────────────────────────────────
    crm: dict = {}
    _SAVE_EVERY = 10  # incremental save every N contacts — if process crashes, progress is preserved
    for i, contact in enumerate(candidates):
        addr  = contact["email"]
        label = contact["name"] or addr
        log(f"Enriching {i + 1}/{len(candidates)}: {label}")
        try:
            enriched = _enrich_contact(
                addr, contact, graph, ai,
                market_segments_content=market_segments_content,
                sent_snippets=sent_by_recipient.get(addr, [])[:5],
            )
        except Exception as e:
            log(f"  Failed: {e}")
            enriched = {
                **contact,
                "company":    _guess_company(addr),
                "role":       "",
                "status":     "other",
                "summary":    "",
                "updated_at": datetime.now().strftime("%Y-%m-%d"),
            }

        # Preserve manually-set fields from previous scan
        old = old_contacts.get(addr, {})
        for field in ("priority", "writing_style", "phone", "linkedin", "ignore"):
            if old.get(field) and not enriched.get(field):
                enriched[field] = old[field]
        if old.get("priority"):
            enriched["priority"] = old["priority"]

        crm[addr] = enriched

        # Incremental save — if the process is killed or hangs later, we don't lose everything
        if (i + 1) % _SAVE_EVERY == 0 or (i + 1) == len(candidates):
            try:
                save_crm(data_dir, {
                    "last_scan":      datetime.now(timezone.utc).isoformat(),
                    "months_scanned": months,
                    "contacts":       crm,
                    "partial":        (i + 1) < len(candidates),
                })
            except Exception as e:
                log(f"  (partial save failed: {e})")

    log(f"CRM build complete — {len(crm)} contacts")
    return {
        "last_scan":      datetime.now(timezone.utc).isoformat(),
        "months_scanned": months,
        "contacts":       crm,
    }


def update_from_email(
    data_dir: Path,
    sender_email: str,
    sender_name: str,
    date_str: str,
) -> None:
    """
    Lightweight update: increment thread_count and refresh last_contact for a sender.
    Called by email monitor on new incoming email, no AI call needed.
    """
    crm = load_crm(data_dir)
    contacts = crm.get("contacts", {})
    addr = sender_email.lower()

    if addr in contacts:
        contacts[addr]["thread_count"] = contacts[addr].get("thread_count", 0) + 1
        if date_str > contacts[addr].get("last_contact", ""):
            contacts[addr]["last_contact"] = date_str
    else:
        contacts[addr] = {
            "email":        addr,
            "name":         sender_name,
            "company":      _guess_company(addr),
            "role":         "",
            "status":       "other",
            "summary":      "",
            "thread_count": 1,
            "last_contact": date_str,
            "updated_at":   date_str,
        }

    crm["contacts"] = contacts
    save_crm(data_dir, crm)


def refresh_crm(
    graph: GraphClient,
    ai,
    data_dir: Path,
    market_segments_content: str = "",
    progress_cb=None,
) -> dict:
    """
    Incremental CRM update. Scans emails since last_scan date.
    - All contacts with new activity: update thread_count + last_contact (no AI)
    - Existing contacts with updated_at > 7 days AND recent activity: re-enrich (AI)
    - New contacts with >= 2 threads in scan window: add + AI-enrich
    Does NOT write to disk — caller must call save_crm().
    """
    def log(msg: str):
        print(f"[CRM] {msg}")
        if progress_cb:
            progress_cb(msg)

    existing = load_crm(data_dir)
    contacts = existing.get("contacts", {})

    # Determine scan window (since last_scan, min 2 days, max 30 days)
    last_scan_str = existing.get("last_scan", "")
    if last_scan_str:
        try:
            last_scan_dt = datetime.fromisoformat(last_scan_str.replace("Z", "+00:00"))
            days_since = max(2, (datetime.now(timezone.utc) - last_scan_dt).days + 1)
            days_since = min(days_since, 30)
        except Exception:
            days_since = 7
    else:
        days_since = 7

    log(f"Incremental refresh — scanning last {days_since} days...")

    try:
        inbox = graph.get_inbox_metadata_since(days=days_since, max_results=500)
    except Exception as e:
        log(f"Inbox scan failed: {e}")
        inbox = []
    try:
        sent = graph.get_sent_messages_since(days=days_since, max_results=500)
    except Exception as e:
        log(f"Sent scan failed: {e}")
        sent = []

    try:
        me = graph.get_me()
        owner_lower = (me.get("mail") or me.get("userPrincipalName") or "").lower()
    except Exception:
        owner_lower = ""

    # Tally activity per contact in scan window
    new_activity: dict = {}
    for msg in inbox:
        ea   = (msg.get("from") or {}).get("emailAddress") or {}
        addr = ea.get("address", "").lower()
        date = (msg.get("receivedDateTime") or "")[:10]
        if not addr or addr == owner_lower or _is_noise(addr):
            continue
        rec = new_activity.setdefault(addr, {"count": 0, "last": date, "name": ea.get("name", "")})
        rec["count"] += 1
        if date > rec["last"]:
            rec["last"] = date

    for msg in sent:
        for r in (msg.get("toRecipients") or []):
            ea   = (r.get("emailAddress") or {})
            addr = ea.get("address", "").lower()
            date = (msg.get("sentDateTime") or "")[:10]
            if not addr or addr == owner_lower or _is_noise(addr):
                continue
            rec = new_activity.setdefault(addr, {"count": 0, "last": date, "name": ea.get("name", "")})
            rec["count"] += 1
            if date > rec["last"]:
                rec["last"] = date

    log(f"{len(new_activity)} contacts with activity in scan window")

    today           = datetime.now().strftime("%Y-%m-%d")
    stale_threshold = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    needs_enrich: list[str] = []

    for addr, activity in new_activity.items():
        if addr in contacts:
            contacts[addr]["thread_count"] = contacts[addr].get("thread_count", 0) + activity["count"]
            if activity["last"] > contacts[addr].get("last_contact", ""):
                contacts[addr]["last_contact"] = activity["last"]
            if contacts[addr].get("updated_at", "") < stale_threshold:
                needs_enrich.append(addr)
        else:
            contacts[addr] = {
                "email":        addr,
                "name":         activity["name"],
                "company":      _guess_company(addr),
                "role":         "", "phone": "", "linkedin": "",
                "status":       "other", "summary": "", "writing_style": "",
                "thread_count": activity["count"],
                "last_contact": activity["last"],
                "updated_at":   "",
            }
            if activity["count"] >= 2:
                needs_enrich.append(addr)

    log(f"{len(needs_enrich)} contacts to re-enrich with AI (capped at 30 per run)")
    for i, addr in enumerate(needs_enrich[:30]):
        label = contacts[addr].get("name") or addr
        log(f"  Re-enriching {i + 1}/{min(len(needs_enrich), 30)}: {label}")
        try:
            enriched = _enrich_contact(
                addr, contacts[addr], graph, ai,
                market_segments_content=market_segments_content,
                sent_snippets=[],
            )
            for field in ("priority", "ignore"):
                if contacts[addr].get(field) is not None:
                    enriched[field] = contacts[addr][field]
            contacts[addr] = enriched
        except Exception as e:
            log(f"  Failed: {e}")
            contacts[addr]["updated_at"] = today

    existing["contacts"]  = contacts
    existing["last_scan"] = datetime.now(timezone.utc).isoformat()
    log(f"Refresh complete — {len(contacts)} total contacts, {len(needs_enrich)} re-enriched")
    return existing
