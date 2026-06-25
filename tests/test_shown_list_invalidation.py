"""After a successful action mutates a domain, the shown-list bucket for that domain is dropped,
so a later '#N' re-resolves against the live store instead of the stale positions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bot import _invalidate_shown_lists, _ACTION_INVALIDATES


def _state():
    return {"_shown_lists": {
        "commitments": {"items": [{"pos": 1, "id": "a"}, {"pos": 2, "id": "b"}]},
        "projects":    {"items": [{"pos": 1, "id": "p1"}]},
        "emails":      {"items": [{"pos": 1, "id": "e1"}]},
        "crm_contacts":{"items": [{"pos": 1, "id": "c1"}]},
    }}


def test_commitment_action_drops_commitments_bucket():
    s = _state()
    _invalidate_shown_lists(s, "mark_commitment_done")
    assert "commitments" not in s["_shown_lists"]      # dropped → next #N re-reads live
    assert "projects" in s["_shown_lists"]              # other domains untouched


def test_modify_project_drops_projects_only():
    s = _state()
    _invalidate_shown_lists(s, "modify_project")
    assert "projects" not in s["_shown_lists"]
    assert "commitments" in s["_shown_lists"] and "emails" in s["_shown_lists"]


def test_crm_action_drops_all_contact_buckets():
    s = _state()
    s["_shown_lists"]["frequency_contacts"] = {"items": []}
    _invalidate_shown_lists(s, "tag_contact")
    for b in ("contacts", "crm_contacts", "frequency_contacts"):
        assert b not in s["_shown_lists"]
    assert "commitments" in s["_shown_lists"]


def test_email_action_drops_emails_bucket():
    s = _state()
    _invalidate_shown_lists(s, "dismiss_email_followup")
    assert "emails" not in s["_shown_lists"]


def test_unknown_or_readonly_tool_noop():
    s = _state()
    _invalidate_shown_lists(s, "get_recent_emails")   # not an action → nothing dropped
    assert set(s["_shown_lists"]) == {"commitments", "projects", "emails", "crm_contacts"}


def test_no_shown_lists_is_safe():
    _invalidate_shown_lists({}, "mark_commitment_done")          # no crash
    _invalidate_shown_lists({"_shown_lists": {}}, "modify_project")


def test_every_mutating_action_is_mapped():
    # guard: the commitments/projects/crm/email mutating tools are all covered
    for t in ("mark_commitment_done", "snooze_commitment", "dismiss_commitment",
              "modify_project", "update_crm_contact", "tag_contact", "dismiss_email_followup"):
        assert t in _ACTION_INVALIDATES and _ACTION_INVALIDATES[t]
