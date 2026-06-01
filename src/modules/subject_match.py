"""
subject_match — shared utilities for deciding whether an email has been
handled outside the "direct reply in same conversationId" path.

Used by:
  - src/sections/reply_needed.py  (5-channel handled detection)
  - src/sections/followup_needed.py (4-channel handled detection)
  - src/bot.py  (check_email_handling tool reads the resulting sidecar)

Single source of truth for:
  1. Subject normalization (Re:/Fwd:/CJK prefix stripping)
  2. The HandlingLink dict shape — both sections MUST go through
     make_handling_link() so consumers (chat tool, frontend) can rely on
     a stable schema.
  3. The two matching primitives find_subject_match / find_meeting_match.

Pure functions, no I/O.
"""
import re
from datetime import datetime


# Recursively-stripped prefixes. Anchored to start, case-insensitive.
# Covers English (re/fw/fwd), German (aw), French (tr), Polish (odp),
# Spanish (rv/res), Czech (vs), Norwegian (sv), Dutch (antw), CJK.
_REPLY_PREFIX = re.compile(
    r"^\s*(re|fw|fwd|aw|tr|sv|antw|res|odp|vs|rv|回复|答复|转发|轉發|回覆)\s*[:\-：]\s*",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")


def normalize_subject(subject: str | None) -> str:
    """Recursively strip Re:/Fwd:/AW:/回复: etc, collapse whitespace, lowercase.

    Returns '' for empty/punctuation-only subjects so callers can short-circuit
    (matching on empty subjects produces false positives — every empty-subject
    email would collide)."""
    if not subject:
        return ""
    s = subject
    # Recursively strip — "Re: Fwd: Re: foo" → "foo". Bounded to avoid
    # pathological inputs; 6 is well beyond any real-world chain depth.
    for _ in range(6):
        new_s = _REPLY_PREFIX.sub("", s)
        if new_s == s:
            break
        s = new_s
    s = _WHITESPACE.sub(" ", s).strip().lower()
    return s


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def make_handling_link(
    *,
    email_id: str,
    email_subject: str,
    email_from: str = "",
    email_to: str = "",
    kind: str,
    target_id: str,
    target_subject: str,
    target_when: str,
    target_link: str = "",
) -> dict:
    """Build a single HandlingLink dict for the results[].handled sidecar.

    kind ∈ {"replied", "drafted", "subject_match_sent",
            "subject_match_draft", "meeting"}

    All sidecar entries — across both reply_needed and followup_needed —
    flow through this function so consumers (chat tool, frontend, audit)
    can depend on a stable shape."""
    return {
        "email_id":      email_id,
        "email_subject": (email_subject or "")[:200],
        "email_from":    (email_from or "").lower(),
        "email_to":      (email_to or "").lower(),
        "handled_by": {
            "kind":           kind,
            "target_id":      target_id or "",
            "target_subject": (target_subject or "")[:200],
            "target_when":    target_when or "",
            "target_link":    target_link or "",
        },
    }


def find_subject_match(
    email_subject: str,
    email_ts: str,
    candidates: list[dict],
    candidate_ts_key: str,
    address_match_fn,
) -> dict | None:
    """Return the most recent candidate whose:
      (a) normalized subject equals email_subject's
      (b) timestamp (read from candidate[candidate_ts_key]) is strictly
          AFTER email_ts
      (c) addressee passes address_match_fn(candidate)

    None when no candidate matches.

    address_match_fn is a closure — reply_needed checks `to ⊇ sender`
    on sent/draft; followup_needed checks `from == recipient` on inbox.
    """
    norm = normalize_subject(email_subject)
    if not norm:
        return None
    email_dt = _parse_iso(email_ts)
    if not email_dt:
        return None
    best: dict | None = None
    best_dt: datetime | None = None
    for c in candidates:
        if not address_match_fn(c):
            continue
        if normalize_subject(c.get("subject")) != norm:
            continue
        c_dt = _parse_iso(c.get(candidate_ts_key))
        if not c_dt or c_dt <= email_dt:
            continue
        if best_dt is None or c_dt > best_dt:
            best = c
            best_dt = c_dt
    return best


def find_meeting_match(
    *,
    email_ts: str,
    contact_email: str,
    events: list[dict],
    max_attendees: int = 12,
) -> dict | None:
    """Calendar event that satisfies all three conditions:
      (a) event.createdDateTime is strictly AFTER email_ts — excludes
          recurring meetings whose series was created long before the email
      (b) attendees include contact_email
      (c) total attendees ≤ max_attendees — excludes all-hands / town halls

    Returns the most-recently-created matching event, or None.

    contact_email is the OTHER party — for reply_needed it's the email's
    sender; for followup_needed it's the email's recipient."""
    contact_lower = (contact_email or "").lower()
    if not contact_lower:
        return None
    email_dt = _parse_iso(email_ts)
    if not email_dt:
        return None
    best: dict | None = None
    best_dt: datetime | None = None
    for evt in events:
        attendees = evt.get("attendees") or []
        if len(attendees) > max_attendees:
            continue
        addrs = {
            ((a.get("emailAddress") or {}).get("address") or "").lower()
            for a in attendees
        }
        if contact_lower not in addrs:
            continue
        created_dt = _parse_iso(evt.get("createdDateTime"))
        if not created_dt or created_dt <= email_dt:
            continue
        if best_dt is None or created_dt > best_dt:
            best = evt
            best_dt = created_dt
    return best
