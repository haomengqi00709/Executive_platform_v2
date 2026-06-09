"""
Snapshot persistence + state-transition detection.

Files in DATA_DIR (env, default ./data):
  fleet_summary.json       — latest snapshot from main backend
  fleet_summary_prev.json  — previous snapshot (rotated by save_current)
  alert_history.json       — {alert_key: last_sent_iso} for dedup

diff(prev, current) is the heart of the monitoring layer: it compares two
snapshots and returns a list of transition events. Each event has a stable
`key` so alerter can dedup re-alerts.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))

# Bot is considered stalled if main backend's snapshot shows last_seen_ts
# older than this. Bots poll Teams every 10s; 10 min of silence = real outage,
# not a transient blip.
BOT_STALL_SECS = 600


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _write_json(p: Path, data):
    _ensure_data_dir()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(p)


def load_current():
    return _read_json(DATA_DIR / "fleet_summary.json", None)


def load_prev():
    return _read_json(DATA_DIR / "fleet_summary_prev.json", None)


def save_current(snapshot):
    """Rotates the current snapshot into _prev before writing the new one,
    so diff() always has a baseline to compare against."""
    current_path = DATA_DIR / "fleet_summary.json"
    prev_path = DATA_DIR / "fleet_summary_prev.json"
    if current_path.exists():
        try:
            prev_path.write_text(current_path.read_text())
        except Exception:
            pass
    _write_json(current_path, snapshot)


def _parse_iso(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _user_status(rec):
    """Distill a user record into (auth_state, bot_state) we monitor.
    Returning None for bot_state means there's no enabled bot to watch."""
    auth_state = (rec.get("health") or {}).get("status") or "unknown"

    bot = rec.get("bot")
    if not bot or not bot.get("enabled"):
        return (auth_state, None)

    last_seen = bot.get("last_seen_ts")
    if not last_seen:
        return (auth_state, "never_seen")

    ts = _parse_iso(last_seen)
    if not ts:
        return (auth_state, "unknown")

    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return (auth_state, "stalled" if age > BOT_STALL_SECS else "active")


def diff(prev, current):
    """Compare two snapshots, return a list of transition events.
    Empty list if either snapshot is missing — we never alert on first poll,
    only on transitions, so the dashboard doesn't spam on cold start."""
    if not prev or not current:
        return []

    prev_by_uid = {u.get("uid"): u for u in (prev.get("users") or []) if u.get("uid")}
    cur_by_uid  = {u.get("uid"): u for u in (current.get("users") or []) if u.get("uid")}

    transitions = []

    for uid, cur in cur_by_uid.items():
        prev_rec = prev_by_uid.get(uid)
        if not prev_rec:
            continue  # new user, no baseline — skip alert this round

        prev_auth, prev_bot = _user_status(prev_rec)
        cur_auth,  cur_bot  = _user_status(cur)

        username = cur.get("username") or uid[:8]

        if prev_auth == "healthy" and cur_auth == "broken":
            transitions.append({
                "type":     "auth_broken",
                "uid":      uid,
                "key":      f"auth_broken:{uid}",
                "username": username,
                "since":    (cur.get("health") or {}).get("broken_since"),
                "error":    (cur.get("health") or {}).get("last_error"),
            })
        elif prev_auth == "broken" and cur_auth == "healthy":
            transitions.append({
                "type":     "auth_recovered",
                "uid":      uid,
                "key":      f"auth_recovered:{uid}",
                "username": username,
                "clears":   f"auth_broken:{uid}",
            })

        # Only fire bot transitions on the active↔stalled edge.
        # never_seen / unknown are skipped to avoid false alerts during startup
        # or after a session is wiped — those don't represent an active outage.
        if prev_bot == "active" and cur_bot == "stalled":
            transitions.append({
                "type":         "bot_stalled",
                "uid":          uid,
                "key":          f"bot_stalled:{uid}",
                "username":     username,
                "last_seen_ts": (cur.get("bot") or {}).get("last_seen_ts"),
            })
        elif prev_bot == "stalled" and cur_bot == "active":
            transitions.append({
                "type":     "bot_recovered",
                "uid":      uid,
                "key":      f"bot_recovered:{uid}",
                "username": username,
                "clears":   f"bot_stalled:{uid}",
            })

    return transitions


def load_alert_history() -> dict:
    return _read_json(DATA_DIR / "alert_history.json", {}) or {}


def record_alert(transition):
    """Record that we just alerted on this transition. Also clears the
    corresponding 'broken' key when a recovery fires, so the next break gets
    a fresh alert instead of being dedup'd."""
    hist = load_alert_history()
    hist[transition["key"]] = datetime.now(timezone.utc).isoformat()
    clears = transition.get("clears")
    if clears and clears in hist:
        del hist[clears]
    _write_json(DATA_DIR / "alert_history.json", hist)


def was_recently_alerted(transition, hours: int) -> bool:
    last = load_alert_history().get(transition["key"])
    if not last:
        return False
    ts = _parse_iso(last)
    if not ts:
        return False
    return (datetime.now(timezone.utc) - ts) < timedelta(hours=hours)
