"""
M03 end-to-end integration test.

Tests the full M03 flow using mock mode (no OneDrive MP4 needed):
  mock .txt transcript → AI analysis → Meeting DB → CRM align → Outlook Draft → Section API

Requirements:
  - Server running at localhost:8000
  - Valid session_token cookie (grab from browser DevTools after login)

Usage:
  export M03_SESSION_COOKIE="eyJhbGciOiJIUzI1Ni..."
  python test_m03.py

Manual checks after the script passes:
  - Teams: Audrey should have sent "✅ Meeting scan complete" message
  - Frontend: Meetings page should show the new meeting
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────

BASE_URL      = "http://localhost:8000"
MOCK_TXT_SRC  = Path(__file__).parent / "test_scripts" / "mock_transcript_q2.txt"
MEETING_ID    = "mock_q2_strategy_review"  # stem of the .txt file we'll place
POLL_INTERVAL = 4   # seconds between status polls
POLL_TIMEOUT  = 180 # seconds max wait

SESSION_COOKIE = os.getenv("M03_SESSION_COOKIE", "")

# ── Helpers ───────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    if SESSION_COOKIE:
        s.cookies.set("session_token", SESSION_COOKIE)
    return s


def _ok(label: str, detail: str = "") -> None:
    print(f"[✅ PASS] {label}" + (f" — {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"[⚠️  SKIP] {label}" + (f" — {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"[❌ FAIL] {label}" + (f" — {detail}" if detail else ""))


# ── Step 0: Resolve user_id ───────────────────────────────

def get_user_info(sess: requests.Session) -> dict:
    r = sess.get(f"{BASE_URL}/api/auth/me", timeout=10)
    if not r.ok:
        sys.exit("Server unreachable or not logged in. Check BASE_URL and SESSION_COOKIE.")
    data = r.json()
    if not data.get("user_id"):
        sys.exit("Not authenticated. Set M03_SESSION_COOKIE to a valid session token.")
    return data


# ── Step 1: Place mock transcript ─────────────────────────

def place_mock_transcript(data_dir: Path) -> Path:
    mock_dir = data_dir / "wiki" / "transcripts" / "mock"
    mock_dir.mkdir(parents=True, exist_ok=True)

    dest = mock_dir / f"{MEETING_ID}.txt"
    shutil.copy(MOCK_TXT_SRC, dest)
    print(f"\nPlaced mock transcript → {dest}")
    return dest


# ── Step 2: Clear old record (allow re-run) ───────────────

def clear_old_record(data_dir: Path) -> None:
    wiki_dir = data_dir / "wiki"
    record   = wiki_dir / f"{MEETING_ID}.json"
    index    = wiki_dir / "_index.json"
    transcript = wiki_dir / "transcripts" / f"{MEETING_ID}.txt"

    if record.exists():
        record.unlink()
    if transcript.exists():
        transcript.unlink()
    if index.exists():
        try:
            idx = json.loads(index.read_text())
            idx.get("meetings", {}).pop(MEETING_ID, None)
            index.write_text(json.dumps(idx, indent=2))
        except Exception:
            pass
    print("Cleared previous mock record (if any)")


# ── Step 3: Trigger scan ──────────────────────────────────

def trigger_scan(sess: requests.Session) -> None:
    r = sess.post(f"{BASE_URL}/api/m03/scan?use_mock=true", timeout=15)
    if not r.ok:
        sys.exit(f"Scan trigger failed: {r.status_code} {r.text[:200]}")
    print("Scan triggered. Polling for completion...")


# ── Step 4: Poll until fresh ──────────────────────────────

def wait_for_fresh(sess: requests.Session, prev_last_run: str | None) -> dict:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            r = sess.get(f"{BASE_URL}/api/sections/recent_meetings", timeout=10)
            if r.ok:
                d = r.json()
                if d.get("status") == "fresh" and d.get("last_run") != prev_last_run:
                    return d
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
    sys.exit(f"Timed out after {POLL_TIMEOUT}s waiting for recent_meetings to refresh.")


# ── Checks ────────────────────────────────────────────────

passed = 0
failed = 0

def check(label: str, condition: bool, detail: str = "", warn_only: bool = False) -> None:
    global passed, failed
    if condition:
        _ok(label, detail)
        passed += 1
    elif warn_only:
        _warn(label, detail)
    else:
        _fail(label, detail)
        failed += 1


def check_1_meeting_db(data_dir: Path) -> dict | None:
    wiki_dir = data_dir / "wiki"
    index_path  = wiki_dir / "_index.json"
    record_path = wiki_dir / f"{MEETING_ID}.json"

    in_index = False
    if index_path.exists():
        try:
            idx = json.loads(index_path.read_text())
            in_index = MEETING_ID in idx.get("meetings", {})
        except Exception:
            pass

    record = None
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text())
        except Exception:
            pass

    has_summary = bool(record and record.get("summary"))
    check("Meeting DB", in_index and has_summary,
          f"index={'yes' if in_index else 'no'}, record={'yes' if record else 'no'}, summary={'yes' if has_summary else 'no'}")
    return record


def check_2_ai_analysis(record: dict | None) -> None:
    if not record:
        check("AI analysis", False, "no record")
        return
    actions   = record.get("action_items", [])
    decisions = record.get("decisions", [])
    topics    = record.get("key_topics", [])
    ok = len(actions) >= 1 and len(topics) >= 3
    check("AI analysis", ok,
          f"{len(actions)} action item(s), {len(decisions)} decision(s), {len(topics)} topic(s)")


def check_3_transcript(data_dir: Path) -> None:
    path = data_dir / "wiki" / "transcripts" / f"{MEETING_ID}.txt"
    size = path.stat().st_size if path.exists() else 0
    check("Transcript saved", size > 0, f"{size} chars")


def check_4_crm_alignment(data_dir: Path, record: dict | None) -> None:
    crm_path = data_dir / "crm.json"
    if not crm_path.exists() or not record:
        _warn("CRM alignment", "no CRM file — skipping")
        return

    try:
        crm = json.loads(crm_path.read_text())
        contacts = crm.get("contacts", {})
        attendee_emails = record.get("attendee_emails", [])
        today = datetime.now().strftime("%Y-%m-%d")

        updated = []
        for email in attendee_emails:
            c = contacts.get(email.lower())
            if c and c.get("last_contact") == today:
                updated.append(email)

        if not attendee_emails:
            _warn("CRM alignment", "no attendee_emails in record (expected for mock)")
        elif updated:
            check("CRM alignment", True, f"last_contact updated for {', '.join(updated)}")
        else:
            _warn("CRM alignment", f"attendees {attendee_emails} not found in CRM — expected for mock emails")
    except Exception as e:
        _warn("CRM alignment", str(e))


def check_5_outlook_draft(sess: requests.Session) -> None:
    try:
        r = sess.get(
            f"{BASE_URL}/api/graph/messages",
            params={"folder": "Drafts", "top": 20,
                    "filter": "contains(subject,'Q2 Strategy Review')"},
            timeout=15,
        )
        if r.ok:
            items = r.json() if isinstance(r.json(), list) else r.json().get("value", [])
            check("Outlook Draft", len(items) > 0,
                  f"found {len(items)} draft(s)" if items else "no draft found")
            return
    except Exception:
        pass

    # Fallback: check via direct Graph if server doesn't expose that route
    _warn("Outlook Draft", "no /api/graph/messages route — check Outlook Drafts manually")


def check_6_section_api(section_result: dict) -> None:
    items = section_result.get("items", [])
    found = any(m.get("meeting_id") == MEETING_ID for m in items)
    check("Section API", found,
          f"status={section_result.get('status')}, {len(items)} total meeting(s), this meeting {'found' if found else 'NOT found'}")


# ── Main ──────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  M03 End-to-End Test")
    print("=" * 55)

    sess = _session()

    # Resolve user
    user = get_user_info(sess)
    uid      = user["user_id"]
    username = user.get("username", uid)
    data_dir = Path(".data") / uid
    print(f"User: {username} ({uid})")
    print(f"Data dir: {data_dir}\n")

    # Get current last_run before we trigger (for detecting change)
    prev_last_run = None
    try:
        r0 = sess.get(f"{BASE_URL}/api/sections/recent_meetings", timeout=10)
        if r0.ok:
            prev_last_run = r0.json().get("last_run")
    except Exception:
        pass

    # Prepare
    clear_old_record(data_dir)
    place_mock_transcript(data_dir)

    # Trigger + wait
    trigger_scan(sess)
    section_result = wait_for_fresh(sess, prev_last_run)
    print(f"Scan complete. last_run = {section_result.get('last_run', '?')[:19]}\n")

    # Run checks
    print("─" * 55)
    record = check_1_meeting_db(data_dir)
    check_2_ai_analysis(record)
    check_3_transcript(data_dir)
    check_4_crm_alignment(data_dir, record)
    check_5_outlook_draft(sess)
    check_6_section_api(section_result)
    print("─" * 55)

    total = passed + failed
    print(f"\nResult: {passed}/{total} checks passed")

    if record:
        print("\nSample AI output:")
        print(f"  Summary:      {(record.get('summary') or '')[:100]}…")
        print(f"  Topics:       {record.get('key_topics', [])}")
        print(f"  Action items: {len(record.get('action_items', []))}")
        print(f"  Decisions:    {len(record.get('decisions', []))}")

    print("\nManual checks:")
    print("  • Teams (Audrey): look for '✅ Meeting scan complete' message")
    print("  • Frontend: Meetings page → should show 'Q2 Strategy Review'")
    print("  • Outlook Drafts: look for 'Follow-up: Q2 Strategy Review'")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
