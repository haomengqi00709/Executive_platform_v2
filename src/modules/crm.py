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

# Bump when the enrichment prompt changes meaningfully — refresh_crm uses this
# to re-enrich existing contacts with the new prompt over the next few days.
PROMPT_VERSION = 2

# Fields AI is allowed to write during enrichment. Everything else (notes, tags,
# meeting_ids, draft_link, priority, ignore, archived, source, manual, added_at)
# is owned by some other module (user UI / m03 / bot / bulk_loader) and must NOT
# be touched by build_crm or refresh_crm.
AI_OWNED_FIELDS = frozenset({
    "company", "role", "phone", "linkedin", "website",
    "status", "summary", "writing_style",
})


# Free / personal email providers — these domains are not company websites,
# so we don't auto-fill `website` from them. Lowercase, no protocol.
_FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.live.com",
    "yahoo.com", "yahoo.co.uk", "yahoo.ca", "ymail.com", "rocketmail.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "aim.com",
    "qq.com", "163.com", "126.com", "sina.com", "foxmail.com",
    "protonmail.com", "proton.me", "pm.me",
    "mail.com", "gmx.com", "gmx.de", "yandex.com", "yandex.ru",
    "zoho.com", "fastmail.com", "tutanota.com", "hey.com",
})


def _guess_website_from_domain(email_addr: str) -> str:
    """If the contact's email domain isn't a free-email provider, treat it as
    the company website. Covers ~80% of business contacts whose signature
    didn't include an explicit URL."""
    if "@" not in email_addr:
        return ""
    domain = email_addr.rsplit("@", 1)[1].lower().strip()
    if not domain or domain in _FREE_EMAIL_DOMAINS:
        return ""
    return f"https://{domain}"


def _merge_ai_enrichment(old: dict, enriched: dict) -> dict:
    """Merge a fresh AI-enriched dict into the existing contact, only touching
    AI-owned fields. Preserves notes / tags / meeting_ids / draft_link /
    priority / ignore / archived / source / manual / added_at — anything that
    isn't AI's to write.

    Rule: for each AI-owned field, the AI's new value wins IF non-empty.
    An empty AI value falls back to the old value (so a transient prompt
    failure doesn't blank out a known-good field)."""
    merged = dict(old)
    for field in AI_OWNED_FIELDS:
        if enriched.get(field):
            merged[field] = enriched[field]
        elif field not in merged:
            merged[field] = ""
    # AI sets these too — derived/timestamp fields
    if enriched.get("updated_at"):
        merged["updated_at"] = enriched["updated_at"]
    # Stamp the prompt version that produced these fields, so refresh_crm can
    # decide whether to re-enrich with a newer prompt.
    merged["prompt_version"] = PROMPT_VERSION
    # Keep email + name (from base) if present
    if enriched.get("email") and "email" not in merged:
        merged["email"] = enriched["email"]
    if enriched.get("name") and not merged.get("name"):
        merged["name"] = enriched["name"]
    # Website fallback: if AI couldn't find one in the signature, derive from
    # the email domain (unless it's a personal email provider).
    if not merged.get("website"):
        merged["website"] = _guess_website_from_domain(merged.get("email", ""))
    return merged


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
    """Derive a company name from the email's domain. Returns "" for
    free-email / personal providers (gmail.com, outlook.com, qq.com, etc.) —
    those addresses identify a person, not a company, and auto-generating
    "Gmail" / "Outlook" / "Qq" as CRM company entries was the dominant
    source of noise in downstream company_intelligence.

    Reuses the same _FREE_EMAIL_DOMAINS allowlist used for website-domain
    derivation (line 39) so the two paths stay in sync."""
    if "@" not in addr:
        return ""
    domain = addr.split("@", 1)[1].lower().strip()
    if not domain or domain in _FREE_EMAIL_DOMAINS:
        return ""
    return domain.split(".")[0].title()


def _enrich_contact(
    addr: str,
    base: dict,
    graph: GraphClient,
    ai: AIClient,
    market_segments_content: str = "",
    business_context: str = "",
    owner_domain: str = "",
    sent_snippets: list[str] | None = None,
) -> dict:
    """Fetch last 5 emails from contact, AI-generate enrichment fields.

    Passing owner_domain and business_context dramatically improves status
    classification — the AI can tell same-domain = internal, and can reason
    about buyer/seller direction from the user's business description."""
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
        "website":       "",
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
        f"\n\nMarket segmentation guide:\n{market_segments_content[:4000]}"
    ) if market_segments_content else ""

    profile_block = (
        f"\n\nABOUT THE USER (whose CRM this is):\n"
        f"{business_context[:4000]}"
    ) if business_context else ""

    rules_block = ""
    if owner_domain:
        rules_block = (
            f"\n\nCLASSIFICATION RULES (apply in order):\n"
            f"1. If the contact's email domain is @{owner_domain} → status = \"internal\"\n"
            f"2. Otherwise reason about the buyer/seller direction using the user's "
            f"business description above:\n"
            f"   - Companies that PAY the user for the user's services/products → \"client\"\n"
            f"   - Early-stage discussions, not yet paying → \"prospect\"\n"
            f"   - Companies the user PAYS for goods/services → \"vendor\"\n"
            f"   - Companies in joint ventures / co-marketing / referral partnerships → \"partner\"\n"
            f"   - Investors / board members / capital providers → \"investor\"\n"
            f"   - Cannot determine from emails → \"other\"\n"
            f"3. An adjacent-industry company is NOT automatically a vendor. Reason from "
            f"the direction of payment, not industry similarity. Example: if the user is "
            f"an engineering DESIGN firm, an engineering EXECUTION firm buying design "
            f"work is a \"client\", not a vendor.\n"
        )

    sent_block = ""
    if sent_snippets:
        sent_block = (
            "\n\nEMAILS THE USER SENT TO THIS CONTACT (most recent first):\n"
            + "\n---\n".join(sent_snippets)
        )

    prompt = (
        f"Analyze these emails from {base.get('name') or addr} and extract structured info."
        f"{profile_block}"
        f"\n\nEMAILS RECEIVED FROM THIS CONTACT:\n{snippets}{sent_block}{seg_block}"
        f"{rules_block}"
        f"\n\nPay close attention to email signatures for name, title, phone, LinkedIn, and company website.\n\n"
        f"Reply ONLY with a JSON object with exactly these keys:\n"
        f"  company: string (from signature or email domain)\n"
        f"  role: string (job title from signature, or empty string)\n"
        f"  phone: string (phone from signature, or empty string)\n"
        f"  linkedin: string (LinkedIn URL from signature, or empty string)\n"
        f"  website: string (company website URL from signature, or empty string)\n"
        f"  status: one of: client, prospect, partner, investor, vendor, internal, other\n"
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
                "website":       parsed.get("website", ""),
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
    """Persist the CRM. Routed through the SQLite store (per-contact rows in one transaction — no
    whole-file corruption race that the old direct crm.json write had); crm.json is regenerated as a
    synced projection so every reader stays unchanged. Edit-preservation for the AI rebuild is kept
    by crm._merge_ai_enrichment upstream (parity with the prior behaviour). Deferred import avoids
    the crm_store→crm cycle."""
    from src.modules import crm_store
    crm_store.replace_from_dict(data_dir, crm)


def update_contact(data_dir: Path, email: str, field: str, value) -> dict:
    """Update a single field on a CRM contact. Creates the contact entry if it doesn't exist.
    'notes' field appends with timestamp instead of overwriting.

    Routed through the SQLite store (atomic per-contact write — no whole-file race with the daily
    rebuild); crm.json is kept synced as a projection so all readers stay unchanged. Deferred
    import avoids the crm_store→crm import cycle."""
    from src.modules import crm_store
    return crm_store.update_contact_field(data_dir, email, field, value)


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
            for f in ("name", "company", "role", "phone", "linkedin", "website"):
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
                "website":     (raw.get("website") or "").strip(),
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


def find_contacts_by_tag_exact(data_dir: Path, tag: str) -> list:
    """Return contacts whose tags contain `tag` as a WHOLE tag (case-insensitive
    EXACT match, not substring). 'Investors' matches the tag 'investors' but NOT
    'potential_investors'. The accurate path for group email, where over-matching
    means emailing the wrong people."""
    crm = load_crm(data_dir)
    tl = (tag or "").strip().lower()
    if not tl:
        return []
    return [
        c for c in crm.get("contacts", {}).values()
        if any(tl == (t or "").strip().lower() for t in (c.get("tags") or []))
    ]


def find_contacts_by_name(data_dir: Path, query: str, limit: int = 10) -> list:
    """Search CRM contacts by name (also matches email local-part and company),
    case-insensitive substring, best matches first. Mirrors find_contacts_by_tag.
    Ranks: exact name > name prefix > name substring > email/company substring.
    Returns up to `limit` compact dicts: {email, name, company, role, tags}."""
    q = (query or "").strip().lower()
    if not q:
        return []
    crm = load_crm(data_dir)
    scored: list = []
    for email, c in (crm.get("contacts") or {}).items():
        name = (c.get("name") or "").strip()
        nl   = name.lower()
        el   = (email or "").lower()
        comp = (c.get("company") or "").lower()
        if nl == q:
            score = 0
        elif nl.startswith(q):
            score = 1
        elif q in nl:
            score = 2
        elif q in el or q in comp:
            score = 3
        else:
            continue
        scored.append((score, nl, {
            "email":   c.get("email") or email,
            "name":    name,
            "company": c.get("company") or "",
            "role":    c.get("role") or "",
            "tags":    c.get("tags") or [],
        }))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _, _, c in scored[:limit]]


def list_groups(data_dir: Path) -> list:
    """Return [{tag, count}, ...] of every distinct tag and how many contacts
    carry it, sorted by count desc then name. Lets callers answer "what groups
    do I have?" and disambiguate a fuzzy group name."""
    crm = load_crm(data_dir)
    counts: dict = {}
    display: dict = {}
    for c in crm.get("contacts", {}).values():
        for t in (c.get("tags") or []):
            t = (t or "").strip()
            if not t:
                continue
            key = t.lower()
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, t)   # first-seen casing for display
    out = [{"tag": display[k], "count": v} for k, v in counts.items()]
    out.sort(key=lambda g: (-g["count"], g["tag"].lower()))
    return out


def resolve_group(data_dir: Path, group: str) -> dict:
    """Resolve a user-typed group name to CRM contacts. Exact-tag match first;
    only if zero exact matches, fall back to substring. Returns:
      {mode: 'exact'|'substring'|'none', matched_tag, contacts,
       candidate_tags: [{tag,count}], all_groups: [{tag,count}]}
    Caller decides: exact → proceed; substring with ONE candidate → proceed;
    substring with >1 → ask the user to pick; none → show all_groups."""
    exact = find_contacts_by_tag_exact(data_dir, group)
    if exact:
        return {"mode": "exact", "matched_tag": (group or "").strip(),
                "contacts": exact, "candidate_tags": [], "all_groups": []}

    crm = load_crm(data_dir)
    gl = (group or "").strip().lower()
    sub_contacts: list = []
    cand: dict = {}
    if gl:
        for c in crm.get("contacts", {}).values():
            hit = [t for t in (c.get("tags") or []) if gl in (t or "").strip().lower()]
            if hit:
                sub_contacts.append(c)
                for t in hit:
                    key = (t or "").strip().lower()
                    rec = cand.setdefault(key, {"tag": (t or "").strip(), "count": 0})
                    rec["count"] += 1
    if sub_contacts:
        return {"mode": "substring", "matched_tag": "", "contacts": sub_contacts,
                "candidate_tags": sorted(cand.values(), key=lambda g: (-g["count"], g["tag"].lower())),
                "all_groups": []}

    return {"mode": "none", "matched_tag": "", "contacts": [],
            "candidate_tags": [], "all_groups": list_groups(data_dir)}


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


def find_contacts_by_emails(data_dir: Path, emails: list) -> list:
    """Return contact dicts for the given emails, in the order requested.

    Only returns contacts that exist in the CRM (the bulk-email feature never
    sends to addresses the user hasn't already vetted as contacts). Lookup is
    by lowercased email, matching how the contacts map is keyed."""
    contacts = load_crm(data_dir).get("contacts", {})
    out = []
    for e in emails or []:
        key = (e or "").strip().lower()
        c = contacts.get(key)
        if c:
            out.append(c)
    return out


def build_crm(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    market_segments_content: str = "",
    business_context: str = "",
    months: int = 6,
    progress_cb=None,
) -> dict:
    """
    Full CRM build from email history.

    Returns {"last_scan": ISO-8601, "months_scanned": int, "contacts": {email: {...}}}.
    Does NOT write to disk — caller must call save_crm().

    Preservation: AI only writes AI-owned fields (see AI_OWNED_FIELDS).
    User edits, m03 meeting links, bot notes, tags, etc. are kept intact via
    _merge_ai_enrichment.
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

    owner_domain = owner_lower.split("@", 1)[1] if "@" in owner_lower else ""

    # ── Phase 6: AI enrich ────────────────────────────────
    # Start from the OLD contacts so dormant entries, manually-created contacts,
    # m03 meeting links, bot notes etc. survive the rescan. We then overlay
    # fresh AI enrichment ONLY for contacts seen in the current scan window.
    crm: dict = {addr: dict(c) for addr, c in old_contacts.items()}
    # Make sure thread_count + last_contact reflect the current scan for everyone
    # the scan saw (they're authoritative for those derived fields).
    for addr, scanned in contacts.items():
        existing = crm.setdefault(addr, {"email": addr})
        existing["thread_count"] = scanned["thread_count"]
        if scanned["last_contact"] > existing.get("last_contact", ""):
            existing["last_contact"] = scanned["last_contact"]
        if not existing.get("name") and scanned.get("name"):
            existing["name"] = scanned["name"]

    _SAVE_EVERY = 10  # incremental save every N contacts — if process crashes, progress is preserved
    for i, contact in enumerate(candidates):
        addr  = contact["email"]
        label = contact["name"] or addr
        log(f"Enriching {i + 1}/{len(candidates)}: {label}")
        try:
            enriched = _enrich_contact(
                addr, contact, graph, ai,
                market_segments_content=market_segments_content,
                business_context=business_context,
                owner_domain=owner_domain,
                sent_snippets=sent_by_recipient.get(addr, [])[:5],
            )
        except Exception as e:
            log(f"  Failed: {e}")
            enriched = {
                "company":    _guess_company(addr),
                "role":       "",
                "status":     "other",
                "summary":    "",
                "updated_at": datetime.now().strftime("%Y-%m-%d"),
            }

        # Merge AI enrichment into existing contact, preserving notes / tags /
        # meeting_ids / draft_link / priority / ignore / archived / source /
        # manual / added_at — every non-AI field is left intact.
        crm[addr] = _merge_ai_enrichment(crm.get(addr, {}), enriched)

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
    business_context: str = "",
    progress_cb=None,
) -> dict:
    """
    Incremental CRM update. Scans emails since last_scan date.
    - All contacts with new activity: update thread_count + last_contact (no AI)
    - Existing contacts with updated_at > 7 days AND recent activity: re-enrich (AI)
    - Existing contacts with old prompt_version: re-enrich (AI), regardless of activity
    - Existing contacts missing AI-owned schema fields: re-enrich (AI)
    - New contacts with >= 2 threads in scan window: add + AI-enrich
    Does NOT write to disk — caller must call save_crm().

    Preservation: AI only writes AI-owned fields. Notes / tags / meeting_ids /
    draft_link / priority / ignore / archived / source / manual / added_at all
    survive across refresh runs.
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

    owner_domain = owner_lower.split("@", 1)[1] if "@" in owner_lower else ""

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
                "role":         "", "phone": "", "linkedin": "", "website": "",
                "status":       "other", "summary": "", "writing_style": "",
                "thread_count": activity["count"],
                "last_contact": activity["last"],
                "updated_at":   "",
            }
            if activity["count"] >= 2:
                needs_enrich.append(addr)

    # Also catch contacts that need re-enrichment for non-activity reasons:
    #   (a) the prompt has changed (PROMPT_VERSION bumped)
    #   (b) we added a new AI-owned field to the schema and this contact is missing it
    # We add them to needs_enrich even without recent activity. Bounded by the
    # 30-per-run cap so a one-time prompt change rolls out over ~1 week instead
    # of slamming the AI in a single run.
    for addr, contact in contacts.items():
        if addr in needs_enrich:
            continue
        if contact.get("prompt_version", 1) < PROMPT_VERSION:
            needs_enrich.append(addr)
            continue
        if any(f not in contact for f in AI_OWNED_FIELDS):
            needs_enrich.append(addr)

    log(f"{len(needs_enrich)} contacts to re-enrich with AI (capped at 30 per run)")
    for i, addr in enumerate(needs_enrich[:30]):
        label = contacts[addr].get("name") or addr
        log(f"  Re-enriching {i + 1}/{min(len(needs_enrich), 30)}: {label}")
        try:
            enriched = _enrich_contact(
                addr, contacts[addr], graph, ai,
                market_segments_content=market_segments_content,
                business_context=business_context,
                owner_domain=owner_domain,
                sent_snippets=[],
            )
            contacts[addr] = _merge_ai_enrichment(contacts[addr], enriched)
        except Exception as e:
            log(f"  Failed: {e}")
            contacts[addr]["updated_at"] = today

    existing["contacts"]  = contacts
    existing["last_scan"] = datetime.now(timezone.utc).isoformat()
    log(f"Refresh complete — {len(contacts)} total contacts, {len(needs_enrich)} re-enriched")
    return existing
