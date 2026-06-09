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


def run() -> None:
    main_url = (os.getenv("MAIN_BACKEND_URL") or "").rstrip("/")
    token    = os.getenv("OPS_ADMIN_TOKEN")
    if not main_url or not token:
        log.warning("MAIN_BACKEND_URL or OPS_ADMIN_TOKEN not set — skipping poll")
        return

    url = f"{main_url}/api/admin/fleet-health"
    try:
        r = requests.get(url, headers={"X-Admin-Token": token}, timeout=30)
    except Exception as e:
        log.warning("fleet-health unreachable: %s", e)
        return

    if r.status_code != 200:
        log.warning("fleet-health %s: %s", r.status_code, r.text[:200])
        return

    try:
        snapshot = r.json()
    except Exception as e:
        log.warning("fleet-health non-JSON: %s", e)
        return

    prev = state.load_current()
    state.save_current(snapshot)

    transitions = state.diff(prev, snapshot)
    if transitions:
        log.info("detected %d transitions: %s", len(transitions),
                 [t["key"] for t in transitions])
        alerter.alert(transitions)
    else:
        log.debug("no transitions (users=%d healthy=%d broken=%d)",
                  snapshot.get("user_count", 0),
                  snapshot.get("healthy", 0),
                  snapshot.get("broken", 0))
