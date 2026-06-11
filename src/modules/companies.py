"""
companies — Company aggregation derived from CRM contacts + Projects.

Storage: .data/{user_id}/companies.json

This is a *derived view*: identity, contacts, projects, derived_status,
last_activity, thread_count_total are recomputed on every build from the
source data (crm.json, projects.json). User-editable fields —
monitor_intelligence, ignore, notes, priority, name — survive across rebuilds.

Two kinds of companies coexist:
  - derived: at least one CRM contact or Project participant references this
    company. Removed when the last reference disappears.
  - manual:  user added the company directly through the Company tab (or via
    one-time migration from market_watchlist.json). Survives with zero
    CRM/Projects links. `manual` is sticky — once True it stays True even if
    derived data later attaches.

Caller owns IO: load_companies / save_companies bookend build_companies,
which returns a dict and never touches disk.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.modules.crm import _FREE_EMAIL_DOMAINS, _guess_company


# Ordered by importance — first match wins when deriving a company's status
# from a mixed bag of its contacts' statuses.
_STATUS_PRIORITY = [
    "client", "prospect", "partner", "investor", "vendor", "internal", "other",
]

# Lowercase suffixes stripped (with leading space) when normalizing the
# company name into the primary key. Punctuation is removed first, so
# "Acme Inc." → "acme inc" → "acme". Order matters — longer alternatives
# before their abbreviations so "limited" beats "ltd" if both could match.
_COMPANY_SUFFIXES = [
    " incorporated",
    " corporation",
    " company",
    " limited",
    " pty ltd",
    " gmbh",
    " llc",
    " llp",
    " inc",
    " corp",
    " ltd",
    " plc",
]


# ── Key normalization ─────────────────────────────────────


def _normalize_name(name: str) -> str:
    """Stable primary key for a company. Lowercase, strip whitespace and
    punctuation, then peel off common legal-form suffixes. Empty string when
    the input isn't a usable company name."""
    s = (name or "").lower().strip()
    if not s:
        return ""
    s = re.sub(r"[,.()\[\]]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for suf in _COMPANY_SUFFIXES:
            if s.endswith(suf):
                s = s[:-len(suf)].strip()
                changed = True
                break
    return s


def _derive_status(contacts: list[dict]) -> str:
    """Most important contact status wins (client > prospect > ... > other)."""
    if not contacts:
        return "other"
    statuses = {(c.get("status") or "other") for c in contacts}
    for s in _STATUS_PRIORITY:
        if s in statuses:
            return s
    return "other"


# ── Domain-based identity ─────────────────────────────────
# A company is identified by its email DOMAIN, not its name. Same domain = same
# company, regardless of how the name was written ("DPS Group" vs domain-fallback
# "Dps"). Personal-email contacts have no business domain and fall back to name.


def _domain_of(email: str) -> str:
    """Business email domain (lowercased), or '' for free-email / no-domain."""
    e = (email or "").lower().strip()
    if "@" not in e:
        return ""
    dom = e.split("@", 1)[1].strip()
    if not dom or dom in _FREE_EMAIL_DOMAINS:
        return ""
    return dom


def _prettify_domain(domain: str) -> str:
    """Last-resort display name from a domain when no real name exists:
    'dps.group' -> 'DPS' (short label as acronym), 'acme.com' -> 'Acme'."""
    label = (domain or "").split(".")[0]
    if not label:
        return domain
    return label.upper() if len(label) <= 4 else label.title()


def _pick_display_name(name_candidates, domain: str, user_name: str = "") -> str:
    """Best display name for a bucket: user edit > a real signature name (one that
    isn't the ugly domain-fallback) > prettified domain > any candidate."""
    if user_name and user_name.strip():
        return user_name.strip()
    fallback = _guess_company("x@" + domain).lower() if domain else ""
    reals = [n.strip() for n in name_candidates
             if n and n.strip() and n.strip().lower() != fallback]
    if reals:
        return max(reals, key=len)            # most complete real name
    if domain:
        return _prettify_domain(domain)
    cands = [n.strip() for n in name_candidates if n and n.strip()]
    return cands[0] if cands else ""


def _merge_company_user_fields(a: dict, b: dict) -> dict:
    """When two old name-keyed records collapse onto one domain key, merge their
    user-editable fields (keep the most-engaged settings)."""
    rank = {"high": 2, "medium": 1, "low": 0}
    names = [x for x in (a.get("name", ""), b.get("name", "")) if (x or "").strip()]
    notes = "\n".join(x for x in (a.get("notes", ""), b.get("notes", "")) if (x or "").strip())
    adds  = [x for x in (a.get("added_at"), b.get("added_at")) if x]
    a_prio, b_prio = a.get("priority", "medium"), b.get("priority", "medium")
    return {
        "name":                 max(names, key=len) if names else "",
        "notes":                notes,
        "priority":             a_prio if rank.get(a_prio, 1) >= rank.get(b_prio, 1) else b_prio,
        # An explicit edit always wins over the other side's default:
        #   monitor default=True  → AND keeps an explicit False
        #   ignore  default=False → OR  keeps an explicit True
        "monitor_intelligence": bool(a.get("monitor_intelligence", True) and b.get("monitor_intelligence", True)),
        "ignore":               bool(a.get("ignore") or b.get("ignore")),
        "manual":               bool(a.get("manual") or b.get("manual")),
        "added_at":             min(adds) if adds else None,
    }


# ── IO ────────────────────────────────────────────────────


def load_companies(data_dir: Path) -> dict:
    f = Path(data_dir) / "companies.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {"last_scan": None, "companies": {}}


def save_companies(data_dir: Path, db: dict) -> None:
    f = Path(data_dir) / "companies.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default


# ── Build ─────────────────────────────────────────────────


def build_companies(data_dir: Path, progress=None) -> dict:
    """
    Rebuild companies.json from crm.json + projects.json.

    User-editable fields (monitor_intelligence, ignore, notes, priority, name)
    are pulled from the existing companies.json (if any) and re-applied to the
    rebuilt records. Manual entries that no longer have any CRM/Projects link
    are kept; derived-only entries whose source data disappeared are removed.

    On first build (no existing companies.json), also migrates names from
    market_watchlist.json as manual entries.

    Pure: doesn't touch disk. Caller must save the result.
    """
    data_dir = Path(data_dir)

    def log(msg: str):
        print(f"[Companies] {msg}")
        if progress:
            progress(msg)

    existing        = load_companies(data_dir)
    existing_by_key = existing.get("companies", {}) or {}
    is_first_build  = not existing_by_key

    crm      = _read_json(data_dir / "crm.json", {"contacts": {}})
    projects = _read_json(data_dir / "projects.json", {"projects": {}})
    contacts_by_email = {
        e.lower(): c for e, c in (crm.get("contacts") or {}).items()
    }

    log(f"Reading {len(contacts_by_email)} CRM contacts, "
        f"{len(projects.get('projects', {}))} projects")

    aggregated: dict[str, dict] = {}

    def bucket(key: str, name_candidate: str = "") -> dict | None:
        """Get-or-create the aggregation bucket for a company KEY (an email
        domain, or a normalized name for personal-email / manual entries).
        name_candidate (a raw company-name string) feeds display-name picking."""
        if not key:
            return None
        bkt = aggregated.get(key)
        if bkt is None:
            bkt = {
                "key":             key,
                "raw_names":       set(),
                "contacts":        [],
                "_contact_keys":   set(),
                "projects":        [],
                "_project_keys":   set(),
                "_from_watchlist": False,
            }
            aggregated[key] = bkt
        if name_candidate and name_candidate.strip():
            bkt["raw_names"].add(name_candidate.strip())
        return bkt

    # ── Pass 1: CRM contacts (keyed by email DOMAIN) ──────
    for email, contact in (crm.get("contacts") or {}).items():
        if contact.get("ignore") or contact.get("archived"):
            continue
        addr = email.lower()
        company = (contact.get("company") or "").strip()
        # Business domain → company identity; personal email → fall back to name.
        key = _domain_of(addr) or _normalize_name(company)
        if not key:
            continue
        bkt = bucket(key, company)
        if bkt is None:
            continue
        if addr in bkt["_contact_keys"]:
            continue
        bkt["_contact_keys"].add(addr)
        bkt["contacts"].append({
            "email":        addr,
            "name":         contact.get("name") or "",
            "role":         contact.get("role") or "",
            "status":       contact.get("status") or "other",
            "last_contact": contact.get("last_contact") or "",
            "thread_count": contact.get("thread_count") or 0,
        })

    log(f"  After CRM pass: {len(aggregated)} unique companies")

    # ── Pass 2: Projects (participant email DOMAIN → company) ──
    for proj_id, proj in (projects.get("projects") or {}).items():
        if proj.get("ignore") or proj.get("archived"):
            continue
        seen_in_project: set[str] = set()
        for email in (proj.get("participants") or []):
            addr = email.lower()
            contact = contacts_by_email.get(addr)
            if not contact:
                continue
            company = (contact.get("company") or "").strip()
            key = _domain_of(addr) or _normalize_name(company)
            if not key or key in seen_in_project:
                continue
            seen_in_project.add(key)
            bkt = bucket(key, company)
            if bkt is None:
                continue
            if proj_id in bkt["_project_keys"]:
                continue
            bkt["_project_keys"].add(proj_id)
            bkt["projects"].append({
                "id":            proj_id,
                "name":          proj.get("name") or "",
                "status":        proj.get("status") or "",
                "last_activity": proj.get("last_activity") or "",
            })

    log(f"  After Projects pass: {len(aggregated)} unique companies")

    # ── Pass 3 (first build only): migrate market_watchlist.json ──
    if is_first_build:
        wl_path = data_dir / "market_watchlist.json"
        if wl_path.exists():
            try:
                names = json.loads(wl_path.read_text()) or []
                migrated = 0
                for name in names:
                    name = str(name).strip()
                    if not name:
                        continue
                    bkt = bucket(_normalize_name(name), name)
                    if bkt is None:
                        continue
                    bkt["_from_watchlist"] = True
                    migrated += 1
                log(f"  Migrated {migrated} entries from market_watchlist.json")
            except Exception as e:
                log(f"  Watchlist migration failed (skipping): {e}")

    # ── Migrate existing user-edits from name-keys to domain-keys ──
    # The key scheme changed (name → domain). Re-map each existing record to its
    # new domain key (from its contacts' emails); records that collapse onto the
    # same domain merge their user fields, so notes / priority / ignore / manual /
    # name survive the migration. Idempotent: already-domain-keyed records map to
    # themselves. Manual / no-business-domain records keep their (name) key.
    migrated: dict[str, dict] = {}
    for old_key, old_rec in existing_by_key.items():
        nk = ""
        for c in (old_rec.get("contacts") or []):
            d = _domain_of(c.get("email", ""))
            if d:
                nk = d
                break
        nk = nk or old_key
        migrated[nk] = (_merge_company_user_fields(migrated[nk], old_rec)
                        if nk in migrated else dict(old_rec))
    existing_by_key = migrated

    # ── Materialize ───────────────────────────────────────
    today   = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    out: dict[str, dict] = {}

    for key, bkt in aggregated.items():
        old = existing_by_key.get(key, {}) or {}

        last_dates = [c["last_contact"] for c in bkt["contacts"] if c["last_contact"]]
        last_dates += [p["last_activity"] for p in bkt["projects"] if p["last_activity"]]
        last_activity = max(last_dates) if last_dates else ""

        thread_count_total = sum(c.get("thread_count", 0) for c in bkt["contacts"])

        # Display name: user-edited > best real (non-domain-fallback) name >
        # prettified domain. A key containing "." is a domain (normalized names
        # have their dots stripped), so we can tell domain-keys from name-keys.
        domain = key if "." in key else ""
        display_name = _pick_display_name(bkt["raw_names"], domain, old.get("name", "")) or key

        # `manual` is sticky — once True (via watchlist migration or
        # user-added through API) it stays True even if derived data later
        # attaches. Lets us tell "user explicitly wants this" from "CRM
        # happens to mention this".
        is_manual = bool(
            bkt["_from_watchlist"]
            or old.get("manual", False)
        )

        out[key] = {
            # Identity (derived, except `name` which can be user-edited)
            "key":     key,
            "name":    display_name,
            "aliases": sorted(bkt["raw_names"]),

            # From CRM / Projects (derived)
            "contacts":           sorted(bkt["contacts"], key=lambda c: c["email"]),
            "contact_count":      len(bkt["contacts"]),
            "projects":           sorted(bkt["projects"], key=lambda p: p["id"]),
            "project_count":      len(bkt["projects"]),
            "derived_status":     _derive_status(bkt["contacts"]),
            "last_activity":      last_activity,
            "thread_count_total": thread_count_total,

            # User-editable (preserved across rebuilds)
            "monitor_intelligence": bool(old.get("monitor_intelligence", True)),
            "ignore":               bool(old.get("ignore", False)),
            "notes":                old.get("notes", "") or "",
            "priority":             old.get("priority", "medium") or "medium",
            "manual":               is_manual,

            # Bookkeeping
            "added_at":   old.get("added_at") or now_iso,
            "updated_at": today,
        }

    # ── Preserve manual-only companies the rebuild didn't surface ──
    # If the user added "Tesla" via the Company tab but no CRM contact or
    # project currently mentions Tesla, the passes above wouldn't surface it.
    # We keep it because the user explicitly asked for it.
    for key, old in existing_by_key.items():
        if key in out:
            continue
        if not old.get("manual"):
            continue
        out[key] = {
            **old,
            "updated_at": today,
        }

    manual_n = sum(1 for c in out.values() if c.get("manual"))
    log(f"Build complete — {len(out)} companies ({manual_n} manual)")

    return {
        "last_scan": now_iso,
        "companies": out,
    }


# ── Single-record edits (used by /api/companies routes) ───


_EDITABLE_FIELDS = frozenset({
    "monitor_intelligence", "ignore", "notes", "priority", "name",
})


def update_company(data_dir: Path, key: str, patch: dict) -> dict:
    """Apply user edits to a single company record. Returns the updated
    record. Raises KeyError if the company doesn't exist."""
    db = load_companies(data_dir)
    companies = db.setdefault("companies", {})
    rec = companies.get(key)
    if rec is None:
        raise KeyError(key)
    for f, v in patch.items():
        if f not in _EDITABLE_FIELDS:
            continue
        rec[f] = v
    rec["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    save_companies(data_dir, db)
    return rec


def add_manual_company(
    data_dir: Path,
    name: str,
    notes: str = "",
    priority: str = "medium",
    monitor_intelligence: bool = True,
) -> dict:
    """Add a user-defined company that doesn't have to exist in CRM/Projects.
    Returns the created record. Raises ValueError for invalid input or
    if the company already exists."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    key = _normalize_name(name)
    if not key:
        raise ValueError("name normalizes to empty")
    db = load_companies(data_dir)
    companies = db.setdefault("companies", {})
    if key in companies:
        raise ValueError(f"company already exists: {companies[key].get('name', key)}")
    now_iso = datetime.now(timezone.utc).isoformat()
    today   = datetime.now().strftime("%Y-%m-%d")
    rec = {
        "key":                  key,
        "name":                 name,
        "aliases":              [name],
        "contacts":             [],
        "contact_count":        0,
        "projects":             [],
        "project_count":        0,
        "derived_status":       "other",
        "last_activity":        "",
        "thread_count_total":   0,
        "monitor_intelligence": bool(monitor_intelligence),
        "ignore":               False,
        "notes":                notes or "",
        "priority":             priority if priority in ("high", "medium", "low") else "medium",
        "manual":               True,
        "added_at":             now_iso,
        "updated_at":           today,
    }
    companies[key] = rec
    save_companies(data_dir, db)
    return rec


def delete_company(data_dir: Path, key: str) -> bool:
    """Remove a company by key. Returns True if removed, False if absent.
    Derived companies will reappear on next build_companies(); manual
    companies are gone for good."""
    db = load_companies(data_dir)
    companies = db.setdefault("companies", {})
    if key not in companies:
        return False
    del companies[key]
    save_companies(data_dir, db)
    return True
