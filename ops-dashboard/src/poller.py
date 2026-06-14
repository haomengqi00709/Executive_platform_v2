"""
Polling loop: pulls /api/admin/fleet-health from the main backend, persists
the snapshot, diffs against the previous one, and hands transitions to the
alerter.

Designed to be called by APScheduler on a fixed interval (default 60s).
Graceful failure: if the main backend is unreachable we log and bail; we do
NOT synthesize a "broken" snapshot, because every user appearing broken at
once should not page Jason 20 times — that's an ops outage, not a fleet
incident.
"""
import logging
import os

import requests

from . import alerter, state

log = logging.getLogger("ops.poller")

POLL_FAIL_THRESHOLD = int(os.getenv("POLL_FAIL_THRESHOLD", "3"))


def run() -> None:
    main_url = (os.getenv("MAIN_BACKEND_URL") or "").rstrip("/")
    token    = os.getenv("OPS_ADMIN_TOKEN")
    if not main_url or not token:
        log.warning("MAIN_BACKEND_URL or OPS_ADMIN_TOKEN not set — skipping poll")
        return

    url = f"{main_url}/api/admin/fleet-health"
    snapshot = None
    err_reason = None
    try:
        r = requests.get(url, headers={"X-Admin-Token": token}, timeout=30)
        if r.status_code != 200:
            err_reason = f"HTTP {r.status_code}: {r.text[:150]}"
        else:
            try:
                snapshot = r.json()
            except Exception as e:
                err_reason = f"non-JSON response: {e}"
    except Exception as e:
        err_reason = f"unreachable: {e}"

    # ── Backend liveness: the one alert that must NOT fail silent. ──
    # We deliberately do NOT synthesize a "broken" snapshot for every user when
    # the backend is unreachable (that would page once per account). Instead we
    # track poll outcomes and fire ONE fleet-level backend alert.
    backend_transitions = state.record_poll_outcome(
        ok=snapshot is not None, err_reason=err_reason,
        threshold=POLL_FAIL_THRESHOLD,
    )
    if backend_transitions:
        log.info("backend transition: %s", [t["type"] for t in backend_transitions])
        alerter.alert(backend_transitions)

    if snapshot is None:
        log.warning("poll failed (%d/%d consecutive): %s",
                    state.load_poll_health().get("consecutive_failures", 0),
                    POLL_FAIL_THRESHOLD, err_reason)
        return

    # ── Per-snapshot detection: only runs on a fresh snapshot. ──
    prev = state.load_current()
    state.save_current(snapshot)

    transitions = state.diff(prev, snapshot)            # auth healthy↔broken (edges)
    transitions += state.detect_job_transitions(snapshot)   # stalled/failing jobs (level)
    transitions += state.detect_pushqa_transitions(snapshot) # low push quality (level)
    if transitions:
        log.info("detected %d transitions: %s", len(transitions),
                 [t["key"] for t in transitions])
        alerter.alert(transitions)
    else:
        log.debug("no transitions (users=%d healthy=%d broken=%d)",
                  snapshot.get("user_count", 0),
                  snapshot.get("healthy", 0),
                  snapshot.get("broken", 0))
