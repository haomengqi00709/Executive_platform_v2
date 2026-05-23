"""
schedules — per-user schedule storage.

Storage: .data/{user_id}/schedules.json

Structure:
{
  "briefings": [
    {
      "id": "morning",           # stable short id (auto-generated if missing)
      "name": "Morning Briefing", # user-visible label
      "enabled": true,
      "cron": "0 7 * * 0-4",     # APScheduler cron (0=Mon, 6=Sun)
      "skills": ["ai_summary", "reply_needed", ...]
    },
    ...
  ],
  "email_monitor": {
    "priority_immediate": true,   # high-priority emails → push immediately
    "interval_minutes":   15,     # batch non-priority every N minutes
    "active_start":       "08:00",
    "active_end":         "20:00"
  },
  "meeting": {
    "prep_enabled":         true,
    "prep_minutes_before":  30,
    "summary_enabled":      true
  }
}
"""
import json
import re
import secrets
from pathlib import Path

_FILENAME = "schedules.json"

# Sections that should NOT appear in a briefing or be schedule-able
# (they're event-triggered or handled by the auto-triggered tools)
NON_SCHEDULABLE_SECTIONS = frozenset({
    "recent_meetings", "meeting_action_items", "expenses",
    "meeting_prep",  # fired by per-meeting poller, not a briefing component
})

DEFAULT_EMAIL_MONITOR = {
    "priority_immediate": True,
    "interval_minutes":   15,
    "active_start":       "08:00",
    "active_end":         "20:00",
}

DEFAULT_MEETING = {
    "prep_enabled":         False,
    "prep_minutes_before":  30,
    "summary_enabled":      True,
}


def load_schedules(data_dir: Path) -> dict:
    """Load schedules.json. Returns full structure with defaults filled in."""
    path = Path(data_dir) / _FILENAME
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            # Old format detection: top-level dict whose values look like {enabled, cron}
            # but no "briefings" key → that's the v1 per-skill format. Drop it.
            if "briefings" not in raw and "email_monitor" not in raw and "meeting" not in raw:
                if raw and all(isinstance(v, dict) and "cron" in v for v in raw.values()):
                    raw = {}
        except Exception:
            raw = {}
    return {
        "briefings":     raw.get("briefings", []) or [],
        "email_monitor": {**DEFAULT_EMAIL_MONITOR, **(raw.get("email_monitor") or {})},
        "meeting":       {**DEFAULT_MEETING,       **(raw.get("meeting")       or {})},
    }


def save_schedules(data_dir: Path, schedules: dict) -> None:
    path = Path(data_dir) / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(schedules, indent=2))
    tmp.replace(path)


# ── Briefings ─────────────────────────────────────────────

def _new_briefing_id() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]


def add_briefing(data_dir: Path, briefing: dict) -> dict:
    schedules = load_schedules(data_dir)
    bid = briefing.get("id") or _new_briefing_id()
    entry = {
        "id":       bid,
        "name":     str(briefing.get("name") or "Untitled").strip()[:80],
        "enabled":  bool(briefing.get("enabled", True)),
        "cron":     str(briefing.get("cron") or "").strip(),
        "tz":       str(briefing.get("tz") or "UTC").strip(),
        "skills":   [s for s in (briefing.get("skills") or []) if isinstance(s, str)],
    }
    if entry["enabled"] and not is_valid_cron(entry["cron"]):
        raise ValueError(f"Invalid cron: {entry['cron']!r}")
    if any(b.get("id") == bid for b in schedules["briefings"]):
        raise ValueError(f"Briefing id collision: {bid}")
    schedules["briefings"].append(entry)
    save_schedules(data_dir, schedules)
    return entry


def update_briefing(data_dir: Path, briefing_id: str, patch: dict) -> dict:
    schedules = load_schedules(data_dir)
    for i, b in enumerate(schedules["briefings"]):
        if b.get("id") == briefing_id:
            merged = {**b, **{k: v for k, v in patch.items() if k in ("name", "enabled", "cron", "tz", "skills")}}
            if merged.get("enabled") and not is_valid_cron(merged.get("cron", "")):
                raise ValueError(f"Invalid cron: {merged.get('cron')!r}")
            schedules["briefings"][i] = merged
            save_schedules(data_dir, schedules)
            return merged
    raise KeyError(f"Briefing '{briefing_id}' not found")


def delete_briefing(data_dir: Path, briefing_id: str) -> None:
    schedules = load_schedules(data_dir)
    before = len(schedules["briefings"])
    schedules["briefings"] = [b for b in schedules["briefings"] if b.get("id") != briefing_id]
    if len(schedules["briefings"]) == before:
        raise KeyError(f"Briefing '{briefing_id}' not found")
    save_schedules(data_dir, schedules)


# ── Auto-triggered tools ──────────────────────────────────

def update_email_monitor(data_dir: Path, patch: dict) -> dict:
    schedules = load_schedules(data_dir)
    em = schedules["email_monitor"]
    if "priority_immediate" in patch:
        em["priority_immediate"] = bool(patch["priority_immediate"])
    if "interval_minutes" in patch:
        try:
            v = int(patch["interval_minutes"])
            if 1 <= v <= 1440:
                em["interval_minutes"] = v
        except Exception:
            pass
    if "active_start" in patch and _valid_hm(patch["active_start"]):
        em["active_start"] = patch["active_start"]
    if "active_end" in patch and _valid_hm(patch["active_end"]):
        em["active_end"] = patch["active_end"]
    schedules["email_monitor"] = em
    save_schedules(data_dir, schedules)
    return em


def update_meeting(data_dir: Path, patch: dict) -> dict:
    schedules = load_schedules(data_dir)
    m = schedules["meeting"]
    if "prep_enabled" in patch:
        m["prep_enabled"] = bool(patch["prep_enabled"])
    if "prep_minutes_before" in patch:
        try:
            v = int(patch["prep_minutes_before"])
            if 5 <= v <= 240:
                m["prep_minutes_before"] = v
        except Exception:
            pass
    if "summary_enabled" in patch:
        m["summary_enabled"] = bool(patch["summary_enabled"])
    schedules["meeting"] = m
    save_schedules(data_dir, schedules)
    return m


# ── Cron helpers ──────────────────────────────────────────

_CRON_FIELD = re.compile(r"^[0-9*,\-/]+$")


def is_valid_cron(expr: str) -> bool:
    if not expr or not isinstance(expr, str):
        return False
    parts = expr.split()
    if len(parts) != 5:
        return False
    return all(_CRON_FIELD.match(p) for p in parts)


def cron_to_apscheduler_kwargs(expr: str) -> dict:
    minute, hour, day, month, dow = expr.split()
    return {
        "minute":      minute,
        "hour":        hour,
        "day":         day,
        "month":       month,
        "day_of_week": dow,
    }


def _valid_hm(s: str) -> bool:
    if not isinstance(s, str):
        return False
    parts = s.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False
