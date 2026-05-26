"""
Fast test for the project-detection + draft-creation changes.
Reuses cached meeting records from wiki/ (no mp4 re-download, no re-transcription).

What we test:
  1. _attendees_from_calendar() lookup for each of the 3 OneDrive meetings
  2. _detect_project() with new prompt (no domain pre-filter)
  3. graph.create_draft() with multi-recipient list (or empty list for draft-without-recipients)
  4. _align_crm() updates contact meeting_ids
  5. _align_projects() updates project meeting_ids

Run from project root:
    python test_m03_quick.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from src import auth
from src.ai import AIClient
from src.graph import GraphClient
from src.modules.m03_meeting import (
    _attendees_from_calendar, _filter_draft_recipients,
    _detect_project, _generate_followup_draft,
    _align_crm, _align_projects,
)

UID = "cd2162aa-61f2-4d28-bce1-dc2332a0a97b"
DATA_DIR = Path(f".data/{UID}")
WIKI_DIR = DATA_DIR / "wiki"

MEETINGS = [
    "ondrive_01NVGOFCM67XC5CJ",  # Team catch up — has Sarah + Ben in record
    "ondrive_01NVGOFCKXY25TN6",  # Second catch up — empty attendees, 11 actions
    "ondrive_01NVGOFCPTSIJNK3",  # Meeting with Jason Hao — empty, 1 action
]


def main():
    token = auth.get_valid_access_token(UID)
    graph = GraphClient(token)
    ai    = AIClient()
    settings = json.loads((DATA_DIR / "settings.json").read_text())
    own_email = (settings.get("report_email") or settings.get("username") or "").lower()
    user_instruction = ""
    instr_path = DATA_DIR / "instructions" / "m03_meeting.md"
    if instr_path.exists():
        user_instruction = instr_path.read_text().strip()

    print("=" * 70)
    print(f" Quick m03 test — own_email={own_email}")
    print("=" * 70)

    for mid in MEETINGS:
        rec_path = WIKI_DIR / f"{mid}.json"
        if not rec_path.exists():
            print(f"\n--- {mid}: NO CACHED RECORD ---")
            continue

        record = json.loads(rec_path.read_text())
        print(f"\n--- {record.get('title', mid)} ---")

        # Look up the original OneDrive item to feed _attendees_from_calendar
        # which expects rec with createdBy/lastModifiedBy etc.
        # We'll just call the calendar lookup via item_id reconstruction.
        item_id_short = mid.replace("ondrive_", "")
        # Find full item in OneDrive Recordings/
        try:
            all_recordings = graph.list_drive_folder("Recordings")
            rec_item = next(
                (r for r in all_recordings if r.get("id", "").startswith(item_id_short)),
                None,
            )
        except Exception as e:
            print(f"  Could not fetch OneDrive list: {e}")
            rec_item = None

        # === Step 1: Calendar attendees ===
        attendees_info = []
        if rec_item:
            attendees_info = _attendees_from_calendar(rec_item, graph) or []
            if attendees_info:
                print(f"  [Calendar] {len(attendees_info)} attendee(s): "
                      f"{[a.get('email') for a in attendees_info]}")
            else:
                print(f"  [Calendar] no match")
        else:
            print(f"  [Calendar] skipped (recording item not found)")

        # External attendees
        external = [a for a in attendees_info if a["email"].lower() != own_email]
        external = _filter_draft_recipients(external, user_instruction, own_email, ai)
        attendee_emails = [a["email"] for a in external]
        print(f"  External attendees after filter: {attendee_emails}")

        # === Step 2: AI project detection ===
        project_id = _detect_project(
            attendee_emails, DATA_DIR,
            title=record.get("title", ""),
            summary=record.get("summary", ""),
            ai=ai,
        )
        print(f"  → project_id: {project_id or '(none)'}")

        # === Step 3: Create draft ===
        draft_body = _generate_followup_draft(record)
        subj = f"Follow-up: {record.get('title', 'our meeting')}"
        html = draft_body.replace("\n", "<br>")
        try:
            resp = graph.create_draft(subj, html, attendee_emails)
            link = resp.get("webLink", "")
            print(f"  → Draft saved ({len(attendee_emails)} recipients): {link[:80]}")
        except Exception as e:
            print(f"  → Draft failed: {e}")

        # === Step 4: Align CRM ===
        _align_crm(attendee_emails, record.get("date", ""), mid, DATA_DIR)

        # === Step 5: Align projects ===
        if project_id:
            _align_projects(project_id, record.get("date", ""), mid, DATA_DIR)

    # Final state check
    print("\n" + "=" * 70)
    print(" FINAL STATE")
    print("=" * 70)
    crm = json.loads((DATA_DIR / "crm.json").read_text())
    proj = json.loads((DATA_DIR / "projects.json").read_text())
    sarah = crm["contacts"].get("sarah.chen@techcorp.com", {})
    ben = crm["contacts"].get("ben.tran@techcorp.com", {})
    print(f"sarah.chen meeting_ids: {sarah.get('meeting_ids', [])}")
    print(f"ben.tran   meeting_ids: {ben.get('meeting_ids', [])}")
    for pid, p in proj["projects"].items():
        if p.get("meeting_ids"):
            print(f"Project [{pid}] meeting_ids: {p['meeting_ids']}")


if __name__ == "__main__":
    main()
