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

    def bucket(raw_name: str) -> dict | None:
        """Get-or-create the aggregation bucket for a company name. Returns
        None when the name normalizes to empty (e.g. just punctuation)."""
        key = _normalize_name(raw_name)
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
        bkt["raw_names"].add(raw_name.strip())
        return bkt

    # ── Pass 1: CRM contacts ──────────────────────────────
    for email, contact in (crm.get("contacts") or {}).items():
        if contact.get("ignore") or contact.get("archived"):
            continue
        company = (contact.get("company") or "").strip()
        if not company:
            continue
        bkt = bucket(company)
        if bkt is None:
            continue
        addr = email.lower()
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

    # ── Pass 2: Projects (linked through participant emails) ──
    for proj_id, proj in (projects.get("projects") or {}).items():
        if proj.get("ignore") or proj.get("archived"):
            continue
        seen_in_project: set[str] = set()
        for email in (proj.get("participants") or []):
            contact = contacts_by_email.get(email.lower())
            if not contact:
                continue
            company = (contact.get("company") or "").strip()
            if not company:
                continue
            key = _normalize_name(company)
            if not key or key in seen_in_project:
                continue
            seen_in_project.add(key)
            bkt = bucket(company)
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
                    bkt = bucket(name)
                    if bkt is None:
                        continue
                    bkt["_from_watchlist"] = True
                    migrated += 1
                log(f"  Migrated {migrated} entries from market_watchlist.json")
            except Exception as e:
                log(f"  Watchlist migration failed (skipping): {e}")

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

        # Display name precedence: user-edited > longest raw alias > key
        if old.get("name"):
            display_name = old["name"]
        elif bkt["raw_names"]:
            display_name = max(bkt["raw_names"], key=len)
        else:
            display_name = key

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
