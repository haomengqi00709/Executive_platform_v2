"""is_attendance_action_item — distinguishes "attend an event" (a calendar
event that resolves when its time passes) from a real deliverable.

The 14 samples below are the actual extracted action items from a live client's
2026-06-02 meeting (the bug report: 3 attendance items stuck in overdue, while
11 real deliverables must keep showing). Locking them prevents regressions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules.text_utils import is_attendance_action_item  # noqa: E402


# Real client data — these 3 are attendance, must be detected (→ dropped when past-due)
DROP = [
    "Attend the meeting with the partner in Thailand (Thursday night)",
    "Attend the meeting with David from the UK (Friday morning)",
    "Attend the meeting with the partner in Thailand (Friday morning)",
]

# Real client data — genuine deliverables, must NEVER be flagged (several name a "meeting"/"call")
KEEP = [
    "Digest the presented technology, create a list of potential target companies",
    "Share the meeting recording and presentation materials with Dave.",
    "Coordinate and schedule a follow-up meeting with Dave for next week",
    "Send snapshots and files of point cloud data from FSD Sky's ongoing project",
    "Review the point cloud data sent by Julien and coordinate a follow-up",
    "Launch the cloud-based SaaS platform for converting point clouds into models",
    "Release the automated Revit model download and conversion solution",
    "Sign the ExxonMobil NDA to move the project forward",
    "Complete website URL modifications and email the link to Max",
    "Email the Excel list of 3D modeling and survey companies to Daniel",
    "Set up the AI outreach tool for Wu and schedule a 5-minute onboarding call",
]


def test_drops_attendance_items():
    for text in DROP:
        assert is_attendance_action_item(text) is True, text


def test_keeps_real_deliverables():
    for text in KEEP:
        assert is_attendance_action_item(text) is False, text


def test_other_attendance_phrasings():
    assert is_attendance_action_item("Join the 3pm call with David") is True
    assert is_attendance_action_item("Be on the partner sync") is True
    assert is_attendance_action_item("Sit in on the design review session") is True
    # "<Name> to attend ..." prefix (no determiner)
    assert is_attendance_action_item("Daniel to attend Thailand meeting") is True


def test_adversarial_negatives():
    # event noun lives in a different clause from the verb → not attendance
    assert is_attendance_action_item("Attend to the invoices. Then schedule a meeting.") is False
    # accepted false negative: "dinner" is not an event noun (upstream prompt catches it)
    assert is_attendance_action_item("Attend the partner dinner (Thursday night)") is False
    # not started by an attendance verb
    assert is_attendance_action_item("Prepare for the Thursday partner meeting") is False
    assert is_attendance_action_item("") is False
    assert is_attendance_action_item(None) is False
