"""
db_cleaner — backend module for finding & resolving DB duplicates and stale records.

Pure backend module. No bot tools; UI (Records → Cleanup tab) and the
weekly scheduler call into this module directly. Candidates are queued in
pending.json and executed when the user (or auto-merge) approves.

Architecture parallel to validator.py / screener.py: a specialised AI pass
that produces structured candidates, plus pure data operations to apply
the approved actions.
"""
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.ai import AIClient


# ── Storage paths ──────────────────────────────────────────

def _cleanup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "db_cleanup"


def _pending_path(data_dir: Path) -> Path:
    return _cleanup_dir(data_dir) / "pending.json"


def _last_scan_path(data_dir: Path) -> Path:
    return _cleanup_dir(data_dir) / "last_scan.json"


def _merge_log_path(data_dir: Path) -> Path:
    return _cleanup_dir(data_dir) / "merge_log.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cand_id(*parts: str) -> str:
    return "cand_" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    from src.storage import atomic_write_json
    atomic_write_json(path, data)


def load_pending(data_dir: Path) -> list[dict]:
    return _read_json(_pending_path(data_dir), [])


def save_pending(data_dir: Path, candidates: list[dict]) -> None:
    _write_json(_pending_path(data_dir), candidates)


def load_last_scan(data_dir: Path) -> dict:
    return _read_json(_last_scan_path(data_dir), {"timestamp": None, "summary": {}})


def _append_merge_log(data_dir: Path, entry: dict) -> None:
    log = _read_json(_merge_log_path(data_dir), [])
    log.append({**entry, "logged_at": _now_iso()})
    _write_json(_merge_log_path(data_dir), log)


# ── Duplicate detection: PROJECTS ──────────────────────────

def _project_signature(p: dict) -> str:
    """Normalised name for cheap pre-filtering."""
    name = (p.get("name") or "").lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# Generic words that don't identify a project's entity — excluded when deciding
# whether two projects share a distinctive company/entity name.
_GENERIC_NAME_WORDS = {
    "project", "projects", "the", "and", "for", "of", "with", "strategy",
    "implementation", "system", "delivery", "assessment", "model", "plan",
    "program", "initiative", "phase", "review", "management", "services",
    "solution", "update", "supply", "chain", "core", "financial",
}


def _name_tokens(name: str) -> list[str]:
    toks = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    return [t for t in toks if len(t) >= 3 and t not in _GENERIC_NAME_WORDS]


def _leading_entity(name: str) -> str:
    """First distinctive token of a project name — usually the company/entity
    (e.g. 'nexus', 'medicare', 'retailmax'). Two projects that lead with the same
    entity are merge candidates even if neither name is a substring of the other
    and they share no participants (the only-owner-participant blind spot)."""
    toks = _name_tokens(name)
    return toks[0] if toks else ""


def _project_pair_features(a: dict, b: dict) -> dict:
    """Heuristic features to feed the AI for high/medium/low confidence."""
    parts_a = set(p.lower() for p in (a.get("participants") or []))
    parts_b = set(p.lower() for p in (b.get("participants") or []))
    shared_parts = parts_a & parts_b

    topics_a = set((t or "").lower() for t in (a.get("key_topics") or []))
    topics_b = set((t or "").lower() for t in (b.get("key_topics") or []))
    shared_topics = topics_a & topics_b

    return {
        "shared_participants": sorted(shared_parts),
        "shared_topics":       sorted(shared_topics),
        "participant_overlap": len(shared_parts),
        "topic_overlap":       len(shared_topics),
    }


def find_duplicate_projects(data_dir: Path, ai: AIClient, progress=None,
                            messages_by_cid: dict = None) -> list[dict]:
    """
    Two-stage detection:
      1. Cheap heuristic: group projects with overlapping participants / similar names /
         same leading entity (company name)
      2. AI judges each candidate pair → confidence + reasoning. When messages_by_cid is
         provided (conversationId -> [messages]), the AI reads the projects' actual emails
         instead of only their names/summaries, so it can tell that e.g. a "kickoff" record
         and a "wrap-up" record are the same engagement.
    """
    data_dir = Path(data_dir)
    projects_path = data_dir / "projects.json"
    if not projects_path.exists():
        return []

    db = _read_json(projects_path, {})
    projects = list(db.get("projects", {}).values())
    # Skip archived / ignored
    projects = [p for p in projects if not p.get("ignore") and not p.get("archived")]

    if len(projects) < 2:
        return []

    # Stage 1: build candidate pairs from heuristics
    pairs: list[tuple[dict, dict, dict]] = []
    seen_pair_keys: set = set()
    for i, a in enumerate(projects):
        for b in projects[i + 1:]:
            features = _project_pair_features(a, b)
            sig_a = _project_signature(a)
            sig_b = _project_signature(b)
            name_overlap = bool(sig_a and sig_b and (sig_a in sig_b or sig_b in sig_a))
            ent_a = _leading_entity(a.get("name", ""))
            same_entity = bool(ent_a and ent_a == _leading_entity(b.get("name", "")))

            # Eligibility: ≥2 shared participants OR fuzzy name overlap OR same leading
            # entity (company name) OR ≥2 shared topics. The same-entity rule catches
            # "Nexus Capital — AI Strategy" vs "Nexus Capital AI Opportunity" even when
            # neither name is a substring of the other and participants are owner-only.
            if (features["participant_overlap"] >= 2
                or name_overlap
                or same_entity
                or features["topic_overlap"] >= 2):
                key = tuple(sorted([a["id"], b["id"]]))
                if key in seen_pair_keys:
                    continue
                seen_pair_keys.add(key)
                pairs.append((a, b, features))

    if progress:
        progress(f"Found {len(pairs)} candidate project pairs from heuristics")
    if not pairs:
        return []

    # Stage 2: AI judges each pair
    candidates: list[dict] = []
    for a, b, features in pairs[:40]:  # cap to control cost
        verdict = _ai_judge_project_pair(ai, a, b, features, messages_by_cid)
        if verdict and verdict.get("is_duplicate"):
            confidence = verdict.get("confidence", "low")
            if confidence not in ("high", "medium", "low"):
                confidence = "low"
            candidates.append({
                "id":         _cand_id("project", a["id"], b["id"]),
                "type":       "project_duplicate",
                "primary":    _project_preview(a),
                "duplicate":  _project_preview(b),
                "confidence": confidence,
                "reasoning":  verdict.get("reasoning", ""),
                "discovered_at": _now_iso(),
            })

    if progress:
        progress(f"AI confirmed {len(candidates)} project duplicates")
    return candidates


def _project_preview(p: dict) -> dict:
    return {
        "id":             p.get("id"),
        "name":           p.get("name"),
        "summary":        p.get("summary"),
        "status":         p.get("status"),
        "participants":   p.get("participants", []),
        "key_topics":     p.get("key_topics", []),
        "last_activity":  p.get("last_activity"),
        "thread_count":   p.get("thread_count"),
    }


def _project_email_lines(proj: dict, messages_by_cid: dict | None, limit: int = 10) -> str:
    """Representative real emails behind a project (subject | preview), bounces skipped."""
    if not messages_by_cid:
        return ""
    lines: list[str] = []
    for cid in proj.get("conversation_ids", []):
        for m in messages_by_cid.get(cid, []):
            subj = (m.get("subject") or "").strip()
            if not subj or subj.lower().startswith(("undeliverable", "canceled:", "accepted:", "declined:")):
                continue
            prev = (m.get("bodyPreview") or "").strip()[:90]
            line = f"    - {subj[:80]}" + (f" | {prev}" if prev else "")
            if line not in lines:
                lines.append(line)
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines)


def _ai_judge_project_pair(ai: AIClient, a: dict, b: dict, features: dict,
                           messages_by_cid: dict = None) -> dict | None:
    a_emails = _project_email_lines(a, messages_by_cid)
    b_emails = _project_email_lines(b, messages_by_cid)
    a_block = f"\n  actual emails:\n{a_emails}" if a_emails else ""
    b_block = f"\n  actual emails:\n{b_emails}" if b_emails else ""
    prompt = f"""Are these two projects the SAME engagement, extracted twice from different
email threads? Judge primarily from the ACTUAL EMAILS below, not just the names.

PROJECT A:
- name: {a.get('name')}
- summary: {a.get('summary', '')[:200]}
- key_topics: {', '.join(a.get('key_topics', [])[:8])}{a_block}

PROJECT B:
- name: {b.get('name')}
- summary: {b.get('summary', '')[:200]}
- key_topics: {', '.join(b.get('key_topics', [])[:8])}{b_block}

Shared participants: {features['participant_overlap']} ({', '.join(features['shared_participants'][:5])})

Rules:
- They ARE the same project (duplicate) if the emails show the SAME client / initiative —
  EVEN IF one record covers the kickoff/early phase and the other the wrap-up/later phase, or
  the names differ (e.g. "Audit" vs "Audit Remediation", "Optimization" vs "Supply Chain
  Optimization"). Sequential phases or sub-topics of one engagement = duplicate.
- They are DISTINCT only if the emails show genuinely different initiatives (different
  objective/deliverable for the same client is OK to keep separate, e.g. a strategy engagement
  vs a separate financial-model review).

Return JSON: {{"is_duplicate": true/false, "confidence": "high"|"medium"|"low", "reasoning": "one sentence citing the emails"}}"""
    try:
        raw = ai.extract_json(prompt)
        return json.loads(raw)
    except Exception as e:
        print(f"[db_cleaner] AI judge failed for {a.get('id')} vs {b.get('id')}: {e}")
        return None


# ── Duplicate detection: CONTACTS ──────────────────────────

def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").lower()).strip()


def find_duplicate_contacts(data_dir: Path, ai: AIClient, progress=None) -> list[dict]:
    """
    Group contacts by name+domain hint then ask AI to confirm same-person matches.
    Catches sarah@personal vs schen@acme style aliases.
    """
    data_dir = Path(data_dir)
    crm_path = data_dir / "crm.json"
    if not crm_path.exists():
        return []

    crm = _read_json(crm_path, {})
    contacts = list(crm.get("contacts", {}).values())
    # Skip archived / ignored
    contacts = [c for c in contacts if not c.get("ignore") and not c.get("archived")]

    if len(contacts) < 2:
        return []

    # Group by normalised name (catches same person at different domains)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for c in contacts:
        nm = _normalize_name(c.get("name"))
        if nm and len(nm) >= 3:
            by_name[nm].append(c)

    pairs: list[tuple[dict, dict]] = []
    seen_pair_keys: set = set()
    for nm, group in by_name.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                key = tuple(sorted([a["email"], b["email"]]))
                if key in seen_pair_keys:
                    continue
                seen_pair_keys.add(key)
                pairs.append((a, b))

    if progress:
        progress(f"Found {len(pairs)} candidate contact pairs from name match")
    if not pairs:
        return []

    # AI judges each pair (capped)
    candidates: list[dict] = []
    for a, b in pairs[:30]:
        verdict = _ai_judge_contact_pair(ai, a, b)
        if verdict and verdict.get("is_same_person"):
            confidence = verdict.get("confidence", "low")
            if confidence not in ("high", "medium", "low"):
                confidence = "low"
            candidates.append({
                "id":         _cand_id("contact", a["email"], b["email"]),
                "type":       "contact_duplicate",
                "primary":    _contact_preview(a),
                "duplicate":  _contact_preview(b),
                "confidence": confidence,
                "reasoning":  verdict.get("reasoning", ""),
                "discovered_at": _now_iso(),
            })

    if progress:
        progress(f"AI confirmed {len(candidates)} contact duplicates")
    return candidates


def _contact_preview(c: dict) -> dict:
    return {
        "email":         c.get("email"),
        "name":          c.get("name"),
        "company":       c.get("company"),
        "role":          c.get("role"),
        "status":        c.get("status"),
        "thread_count":  c.get("thread_count"),
        "last_contact":  c.get("last_contact"),
    }


def _ai_judge_contact_pair(ai: AIClient, a: dict, b: dict) -> dict | None:
    prompt = f"""Are these two CRM contacts the same real-world person, just using two different email addresses?

CONTACT A:
- email: {a.get('email')}
- name: {a.get('name')}
- company: {a.get('company', '')}
- role: {a.get('role', '')}
- status: {a.get('status', '')}

CONTACT B:
- email: {b.get('email')}
- name: {b.get('name')}
- company: {b.get('company', '')}
- role: {b.get('role', '')}
- status: {b.get('status', '')}

Return JSON: {{"is_same_person": true/false, "confidence": "high"|"medium"|"low", "reasoning": "one sentence"}}

Confidence rubric:
- high: exact name match + same company → almost certainly same person, just personal+work email
- medium: same name + adjacent companies (acquisition? subsidiary?) → likely same person mid-job-change
- low: name match but companies look unrelated — could be coincidence (common name)
"""
    try:
        raw = ai.extract_json(prompt)
        return json.loads(raw)
    except Exception as e:
        print(f"[db_cleaner] AI judge failed for {a.get('email')} vs {b.get('email')}: {e}")
        return None


# ── Stale detection (no AI, pure date heuristics) ─────────

def _parse_loose_date(s: str) -> datetime | None:
    """Parse YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ formats into naive UTC datetime."""
    if not s:
        return None
    try:
        # Try date-only first (most common in projects/crm)
        if len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d")
        # ISO with timezone
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def find_stale_records(data_dir: Path) -> list[dict]:
    data_dir = Path(data_dir)
    candidates: list[dict] = []
    now = datetime.utcnow()  # naive UTC to match _parse_loose_date output
    six_months_ago  = now - timedelta(days=180)
    twelve_months_ago = now - timedelta(days=365)

    # Stale projects: completed + last_activity > 6 months ago
    proj_path = data_dir / "projects.json"
    if proj_path.exists():
        db = _read_json(proj_path, {})
        for p in db.get("projects", {}).values():
            if p.get("archived") or p.get("ignore"):
                continue
            if p.get("status") != "completed":
                continue
            la = p.get("last_activity") or ""
            la_dt = _parse_loose_date(la)
            if la_dt and la_dt < six_months_ago:
                candidates.append({
                    "id":         _cand_id("stale_project", p["id"]),
                    "type":       "stale_project",
                    "primary":    _project_preview(p),
                    "duplicate":  None,
                    "confidence": "high",  # date-based, deterministic
                    "reasoning":  f"Completed project with last activity {la}",
                    "discovered_at": _now_iso(),
                })

    # Stale contacts: no contact in 12 months AND status == "other"
    crm_path = data_dir / "crm.json"
    if crm_path.exists():
        crm = _read_json(crm_path, {})
        for c in crm.get("contacts", {}).values():
            if c.get("archived") or c.get("ignore"):
                continue
            if c.get("status") != "other":
                continue
            lc = c.get("last_contact") or ""
            lc_dt = _parse_loose_date(lc)
            if lc_dt and lc_dt < twelve_months_ago:
                candidates.append({
                    "id":         _cand_id("stale_contact", c["email"]),
                    "type":       "stale_contact",
                    "primary":    _contact_preview(c),
                    "duplicate":  None,
                    "confidence": "high",
                    "reasoning":  f"No contact since {lc}, status=other",
                    "discovered_at": _now_iso(),
                })

    return candidates


# ── Execution: MERGE operations ────────────────────────────

def merge_projects(data_dir: Path, keep_id: str, merge_id: str) -> dict:
    """Apply a project merge: combine fields, delete the duplicate, log it.

    Persisted through projects_store (the single source of truth) — NOT a direct projects.json write.
    Otherwise the store keeps the merged-away duplicate and the next project refresh resurrects it."""
    from src.modules import projects_store
    data_dir = Path(data_dir)
    projects = projects_store.load_projects(data_dir).get("projects", {})

    if keep_id not in projects or merge_id not in projects:
        return {"ok": False, "error": "Project not found"}

    keep = projects[keep_id]
    merge = projects[merge_id]
    before = {"keep": dict(keep), "merge": dict(merge)}

    # Union: participants, conversation_ids, key_topics
    keep["participants"] = sorted(set(keep.get("participants", []) + merge.get("participants", [])))
    keep["conversation_ids"] = sorted(set(keep.get("conversation_ids", []) + merge.get("conversation_ids", [])))
    keep["key_topics"] = sorted(set(keep.get("key_topics", []) + merge.get("key_topics", [])))
    keep["thread_count"] = (keep.get("thread_count") or 0) + (merge.get("thread_count") or 0)
    # Take later last_activity
    if (merge.get("last_activity") or "") > (keep.get("last_activity") or ""):
        keep["last_activity"] = merge["last_activity"]
    keep["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    # Persist through the store: upsert the merged keep (full object → user cols preserved), then
    # delete the duplicate row so it can't be regenerated into the projection.
    projects_store.replace_from_dict(data_dir, {"projects": {keep_id: keep}})
    projects_store.delete_project(data_dir, merge_id)
    _append_merge_log(data_dir, {
        "op": "merge_projects", "keep_id": keep_id, "merge_id": merge_id, "before": before,
    })
    return {"ok": True, "keep_id": keep_id, "removed_id": merge_id}


# Priority is a scalar STATE, not a list — when two duplicates disagree the stronger one wins
# (you can't keep "two priorities"). Everything below "high/medium/low" ranks 0 so an unset side
# never overrides a set one.
_PRIORITY_RANK = {"high": 3, "medium": 2, "med": 2, "normal": 2, "low": 1}


def _prio_rank(p) -> int:
    return _PRIORITY_RANK.get((p or "").strip().lower(), 0)


def _union_list(*lists) -> list:
    """Order-preserving union of several lists; strings deduped case-insensitively, blanks dropped.
    The merge's list-type fields (tags, aliases, name variants, meeting_ids) use this so NO entry
    from either side is ever lost."""
    out, seen = [], set()
    for lst in lists:
        for v in (lst or []):
            if v is None or v == "":
                continue
            key = v.lower() if isinstance(v, str) else v
            if key in seen:
                continue
            seen.add(key)
            out.append(v)
    return out


def merge_contacts(data_dir: Path, keep_email: str, merge_email: str) -> dict:
    """Apply a contact merge as a LOSSLESS field-level UNION — neither side's data is dropped.

    The previous version was "keep wins": it copied only 6 AI fields from the merged-away side (and
    only when keep's was empty), then deleted the row — silently losing any tags / notes / priority /
    ignore the user had set on that side. That violated "don't lose user customization". The merge now
    folds EVERY field into keep BEFORE deleting the duplicate:
      - list fields (tags, meeting_ids, name variants, email aliases) → UNION, deduped
      - scalar-state flags (ignore / archived / manual) → OR; priority → stronger wins
      - free text (notes / summary / writing_style) → concatenate when the two differ
      - AI/derived single-value fields (role / phone / linkedin / status / …) → non-empty wins, prefer keep
      - company → non-empty wins; if both set and differ, keep primary + record the other in notes
    keep_email stays the canonical address; merge_email and any aliases it carried become aliases, and
    its display name (if different) is preserved under name_variants — so searching either name resolves
    once a reader honours those fields.

    Persisted through crm_store (the single source of truth): upsert the fully-merged keep, then delete
    the duplicate row — so the merge can never lose user data and can't be resurrected from crm.json."""
    from src.modules import crm_store
    data_dir = Path(data_dir)
    contacts = crm_store.load_crm(data_dir).get("contacts", {})

    keep_key  = keep_email.lower()
    merge_key = merge_email.lower()
    if keep_key not in contacts or merge_key not in contacts:
        return {"ok": False, "error": "Contact not found"}

    keep  = dict(contacts[keep_key])
    merge = dict(contacts[merge_key])
    before = {"keep": dict(keep), "merge": dict(merge)}

    # ── counts / derived ──
    keep["thread_count"] = (keep.get("thread_count") or 0) + (merge.get("thread_count") or 0)
    keep["last_contact"] = max(keep.get("last_contact") or "", merge.get("last_contact") or "")
    if merge.get("added_at"):
        keep["added_at"] = min(keep.get("added_at") or merge["added_at"], merge["added_at"])

    # ── list-type fields: UNION, never drop ──
    keep["tags"]        = _union_list(keep.get("tags"), merge.get("tags"))
    keep["meeting_ids"] = _union_list(keep.get("meeting_ids"), merge.get("meeting_ids"))

    # name: one canonical display name (keep's); preserve every other distinct name as a variant
    variants = _union_list(keep.get("name_variants"), merge.get("name_variants"),
                           [keep.get("name"), merge.get("name")])
    variants = [n for n in variants if n and n != keep.get("name")]
    if variants:
        keep["name_variants"] = variants

    # emails: keep_key stays primary; merge's address + any aliases it carried become aliases
    aliases = _union_list(keep.get("aliases"), merge.get("aliases"),
                          [merge.get("email") or merge_key])
    keep["aliases"] = sorted(a for a in aliases if a and a.lower() != keep_key)

    # ── scalar-state flags: combine by rule (never silently drop a flag the user set) ──
    keep["ignore"]   = bool(keep.get("ignore")   or merge.get("ignore"))
    keep["archived"] = bool(keep.get("archived") or merge.get("archived"))
    keep["manual"]   = bool(keep.get("manual")   or merge.get("manual"))
    if _prio_rank(merge.get("priority")) > _prio_rank(keep.get("priority")):
        keep["priority"] = merge["priority"]

    # ── free text: concatenate when the two differ (keep both) ──
    for f in ("notes", "summary", "writing_style"):
        kv = (keep.get(f) or "").strip()
        mv = (merge.get(f) or "").strip()
        if mv and mv != kv:
            keep[f] = f"{kv}\n{mv}".strip()

    # ── AI/derived single-value fields: non-empty wins (prefer keep) ──
    for f in ("role", "phone", "linkedin", "status", "draft_link", "source"):
        if not keep.get(f) and merge.get(f):
            keep[f] = merge[f]

    # company: non-empty wins; if both set and differ, keep primary + record the other in notes
    kc = (keep.get("company") or "").strip()
    mc = (merge.get("company") or "").strip()
    if not kc and mc:
        keep["company"] = mc
    elif kc and mc and kc.lower() != mc.lower():
        note = f"[merge] also listed under company: {mc}"
        existing = (keep.get("notes") or "").strip()
        keep["notes"] = f"{existing}\n{note}".strip()

    keep["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    # Persist through the store: upsert the fully-merged keep, THEN delete the duplicate row.
    crm_store.replace_from_dict(data_dir, {"contacts": {keep_key: keep}})
    crm_store.delete_contact(data_dir, merge_key)
    _append_merge_log(data_dir, {
        "op": "merge_contacts", "keep_email": keep_email, "merge_email": merge_email, "before": before,
    })
    return {"ok": True, "keep_email": keep_email, "removed_email": merge_email}


def archive_record(data_dir: Path, kind: str, ident: str) -> dict:
    """Set archived=true on a project (kind='project') or contact (kind='contact').

    Field-level write through the store (the single source of truth) — so the archived flag survives
    the next refresh instead of being a direct JSON write that gets regenerated away."""
    data_dir = Path(data_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    if kind == "project":
        from src.modules import projects_store
        updated = projects_store.update_project_fields(data_dir, ident, {"archived": True}, today)
        if updated is None:
            return {"ok": False, "error": "Project not found"}
    elif kind == "contact":
        from src.modules import crm_store
        e = ident.lower()
        # update_contact_field creates the row if absent — guard existence first to keep the 404.
        if e not in crm_store.load_crm(data_dir).get("contacts", {}):
            return {"ok": False, "error": "Contact not found"}
        crm_store.update_contact_field(data_dir, e, "archived", True)
        crm_store.update_contact_field(data_dir, e, "updated_at", today)
    else:
        return {"ok": False, "error": f"Unknown kind: {kind}"}

    _append_merge_log(data_dir, {"op": "archive", "kind": kind, "id": ident})
    return {"ok": True}


# ── Orchestration: scan + approve ──────────────────────────

def run_full_scan(data_dir: Path, ai: AIClient, progress=None) -> dict:
    """Run all three detection passes and write pending.json + last_scan.json."""
    data_dir = Path(data_dir)

    def log(msg: str):
        if progress:
            progress(msg)
        print(f"[db_cleaner] {msg}")

    log("Scanning for duplicate projects...")
    project_cands = find_duplicate_projects(data_dir, ai, progress=log)
    log("Scanning for duplicate contacts...")
    contact_cands = find_duplicate_contacts(data_dir, ai, progress=log)
    log("Scanning for stale records...")
    stale_cands = find_stale_records(data_dir)

    all_candidates = project_cands + contact_cands + stale_cands

    # Preserve previously-dismissed candidates so we don't re-surface them
    previous = load_pending(data_dir)
    dismissed_ids = {c["id"] for c in previous if c.get("status") == "dismissed"}
    all_candidates = [c for c in all_candidates if c["id"] not in dismissed_ids]

    save_pending(data_dir, all_candidates)

    summary = {
        "high":   sum(1 for c in all_candidates if c["confidence"] == "high"   and c["type"] in ("project_duplicate", "contact_duplicate")),
        "medium": sum(1 for c in all_candidates if c["confidence"] == "medium" and c["type"] in ("project_duplicate", "contact_duplicate")),
        "low":    sum(1 for c in all_candidates if c["confidence"] == "low"    and c["type"] in ("project_duplicate", "contact_duplicate")),
        "stale":  sum(1 for c in all_candidates if c["type"] in ("stale_project", "stale_contact")),
        "total":  len(all_candidates),
    }
    _write_json(_last_scan_path(data_dir), {
        "timestamp": _now_iso(),
        "summary":   summary,
    })
    log(f"Scan complete: {summary}")
    return {"summary": summary, "candidates": all_candidates}


def approve_candidates(data_dir: Path, candidate_ids: list[str]) -> dict:
    """Execute the action(s) implied by each candidate. Returns counts."""
    data_dir = Path(data_dir)
    pending = load_pending(data_dir)
    by_id = {c["id"]: c for c in pending}

    counts = {"merged_projects": 0, "merged_contacts": 0, "archived": 0, "errors": []}
    for cid in candidate_ids:
        c = by_id.get(cid)
        if not c:
            counts["errors"].append(f"Candidate {cid} not found")
            continue
        if c["type"] == "project_duplicate":
            r = merge_projects(data_dir, c["primary"]["id"], c["duplicate"]["id"])
            if r.get("ok"):
                counts["merged_projects"] += 1
            else:
                counts["errors"].append(f"{cid}: {r.get('error')}")
        elif c["type"] == "contact_duplicate":
            r = merge_contacts(data_dir, c["primary"]["email"], c["duplicate"]["email"])
            if r.get("ok"):
                counts["merged_contacts"] += 1
            else:
                counts["errors"].append(f"{cid}: {r.get('error')}")
        elif c["type"] == "stale_project":
            r = archive_record(data_dir, "project", c["primary"]["id"])
            if r.get("ok"):
                counts["archived"] += 1
            else:
                counts["errors"].append(f"{cid}: {r.get('error')}")
        elif c["type"] == "stale_contact":
            r = archive_record(data_dir, "contact", c["primary"]["email"])
            if r.get("ok"):
                counts["archived"] += 1
            else:
                counts["errors"].append(f"{cid}: {r.get('error')}")

    # Remove approved from pending
    remaining = [c for c in pending if c["id"] not in candidate_ids]
    save_pending(data_dir, remaining)
    return counts


def reject_candidates(data_dir: Path, candidate_ids: list[str]) -> dict:
    """Mark candidates as dismissed so they don't reappear in the next scan."""
    pending = load_pending(data_dir)
    for c in pending:
        if c["id"] in candidate_ids:
            c["status"] = "dismissed"
            c["dismissed_at"] = _now_iso()
    save_pending(data_dir, pending)
    return {"dismissed": len(candidate_ids)}


# ── Teams Adaptive Card weekly digest ──────────────────────

def build_digest_card(summary: dict, cleanup_url: str, auto_applied: int = 0) -> dict:
    """Adaptive Card for the weekly Monday cleanup digest.

    summary keys: high, medium, low, stale, total
    auto_applied: count of candidates auto-merged/archived under user's settings
    cleanup_url: deeplink to Records → Cleanup tab on the web app
    """
    high   = summary.get("high", 0)
    medium = summary.get("medium", 0)
    low    = summary.get("low", 0)
    stale  = summary.get("stale", 0)
    total  = summary.get("total", 0)

    body: list = [
        {
            "type": "TextBlock",
            "text": "🧹 Weekly DB Cleanup",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "TextBlock",
            "text": datetime.now(timezone.utc).strftime("%B %d, %Y"),
            "isSubtle": True,
            "spacing": "None",
        },
    ]

    if total == 0 and auto_applied == 0:
        body.append({
            "type": "TextBlock",
            "text": "✅ Nothing to clean — your DB looks tidy.",
            "wrap": True,
            "separator": True,
        })
    else:
        if auto_applied:
            body.append({
                "type": "TextBlock",
                "text": f"✅ Auto-applied {auto_applied} candidate{'s' if auto_applied != 1 else ''} this week.",
                "color": "Good",
                "separator": True,
                "wrap": True,
            })

        rows = []
        if high:   rows.append(f"🟢 **HIGH** confidence duplicates: {high}")
        if medium: rows.append(f"🟡 **MEDIUM** confidence: {medium}")
        if low:    rows.append(f"⚪ **LOW** confidence: {low}")
        if stale:  rows.append(f"📦 **Stale** records: {stale}")

        if rows:
            body.append({
                "type": "TextBlock",
                "text": "Awaiting your review:",
                "weight": "Bolder",
                "separator": True,
            })
            for r in rows:
                body.append({
                    "type": "TextBlock",
                    "text": r,
                    "wrap": True,
                    "spacing": "Small",
                })

    actions = []
    if total > 0:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "Review on web →",
            "url": cleanup_url,
        })

    card: dict = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card
