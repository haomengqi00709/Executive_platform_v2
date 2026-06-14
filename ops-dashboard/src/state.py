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

# NOTE: We deliberately do not monitor bot last_seen_ts for stall detection.
# That field tracks "last inbound message from owner", NOT polling heartbeat,
# so a bot the owner hasn't messaged for days reads as "stalled" while being
# perfectly healthy. Real bot polling outages surface via auth_health (token
# expiry is the dominant failure mode); we monitor that instead.


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


# ── Backend poll liveness (stream 1: heartbeat) ───────────
# Separate from per-user health: tracks whether the ops poller can reach the
# main backend at all. A total backend outage must surface as ONE fleet-level
# alert, never as N per-user "broken" alerts.

_POLL_HEALTH_DEFAULT = {
    "status": "ok",            # ok | down
    "consecutive_failures": 0,
    "last_success_at": None,
    "last_failure_at": None,
    "last_error": None,
    "down_since": None,
}


def load_poll_health() -> dict:
    h = _read_json(DATA_DIR / "poll_health.json", None)
    return h if isinstance(h, dict) else dict(_POLL_HEALTH_DEFAULT)


def save_poll_health(h: dict):
    _write_json(DATA_DIR / "poll_health.json", h)


def record_poll_outcome(ok: bool, err_reason, threshold: int) -> list:
    """Update poll-liveness state and return backend transition events.

    Emits `backend_unreachable` once the failure streak reaches `threshold`,
    and on every poll thereafter while still down (alerter dedups to one page
    per ALERT_REPEAT_HOURS, same as auth breaks). Emits `backend_recovered` on
    the first successful poll after a down period."""
    h = load_poll_health()
    now = _now_iso()
    transitions = []

    if ok:
        was_down = h.get("status") == "down"
        down_since = h.get("down_since")
        h.update({
            "status": "ok",
            "consecutive_failures": 0,
            "last_success_at": now,
            "last_error": None,
            "down_since": None,
        })
        save_poll_health(h)
        if was_down:
            transitions.append({
                "type":       "backend_recovered",
                "key":        "backend_recovered",
                "clears":     "backend_unreachable",
                "down_since": down_since,
            })
    else:
        h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
        h["last_failure_at"] = now
        h["last_error"] = err_reason
        if h["consecutive_failures"] >= threshold:
            if h.get("status") != "down":
                h["status"] = "down"
                h["down_since"] = now
            transitions.append({
                "type":        "backend_unreachable",
                "key":         "backend_unreachable",
                "since":       h.get("down_since") or now,
                "error":       err_reason,
                "consecutive": h["consecutive_failures"],
            })
        save_poll_health(h)

    return transitions


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


def _auth_status(rec) -> str:
    return (rec.get("health") or {}).get("status") or "unknown"


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

        prev_auth = _auth_status(prev_rec)
        cur_auth  = _auth_status(cur)
        username  = cur.get("username") or uid[:8]

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

    return transitions


# ── Scheduler job health + push-quality transitions (streams 2 & 4) ──
# Level-based conditions (a job is stalled / a user's quality is low) rather
# than snapshot edges, so — like backend liveness — we emit on every poll while
# the condition holds and let the alerter's 6h dedup gate re-pages. Recovery is
# detected via the alert_history key, which record_alert() clears.

_JOB_FAIL_THRESHOLD = int(os.getenv("JOB_FAIL_THRESHOLD", "5"))


def _job_is_stale(rec: dict, now) -> bool:
    """A job is unhealthy if it's failed many times in a row OR hasn't succeeded
    within ~3× its expected cadence (min 5 min grace, to avoid flapping on the
    10s bot poll). Unknown-cadence jobs are never flagged."""
    if rec.get("consecutive_failures", 0) >= _JOB_FAIL_THRESHOLD:
        return True
    exp = rec.get("expected_interval_secs")
    if not exp:
        return False
    threshold = max(exp * 3, 300)
    last = _parse_iso(rec.get("last_success"))
    if not last:
        lr = _parse_iso(rec.get("last_run"))
        return bool(lr) and (now - lr).total_seconds() > threshold
    return (now - last).total_seconds() > threshold


def detect_job_transitions(snapshot: dict) -> list:
    now = datetime.now(timezone.utc)
    hist = load_alert_history()
    transitions = []
    for j in (snapshot.get("jobs") or []):
        jid = j.get("job_id")
        if not jid:
            continue
        if _job_is_stale(j, now):
            transitions.append({
                "type":         "job_stale",
                "key":          f"job_stale:{jid}",
                "job_id":       jid,
                "last_success": j.get("last_success"),
                "error":        j.get("last_error"),
                "consecutive":  j.get("consecutive_failures", 0),
            })
        elif f"job_stale:{jid}" in hist:
            transitions.append({
                "type":   "job_recovered",
                "key":    f"job_recovered:{jid}",
                "job_id": jid,
                "clears": f"job_stale:{jid}",
            })
    return transitions


def detect_pushqa_transitions(snapshot: dict) -> list:
    pq = snapshot.get("push_qa")
    if not pq:
        return []
    hist = load_alert_history()
    transitions = []
    for u in (pq.get("users") or []):
        uid = u.get("uid")
        if not uid:
            continue
        if u.get("fail", 0) > 0:
            failed = [s.get("section_id") for s in (u.get("sections") or [])
                      if s.get("verdict") == "fail"]
            transitions.append({
                "type":     "pushqa_low",
                "key":      f"pushqa_low:{uid}",
                "uid":      uid,
                "username": u.get("username") or uid[:8],
                "fail":     u.get("fail", 0),
                "sections": failed,
            })
        elif f"pushqa_low:{uid}" in hist:
            transitions.append({
                "type":     "pushqa_recovered",
                "key":      f"pushqa_recovered:{uid}",
                "uid":      uid,
                "username": u.get("username") or uid[:8],
                "clears":   f"pushqa_low:{uid}",
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
