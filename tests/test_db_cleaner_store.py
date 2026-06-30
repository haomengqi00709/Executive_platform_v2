"""db_cleaner now persists merges/archives through the SQLite store, not direct JSON writes.

THE headline guarantee: after a merge/archive, the change lives in the store — so a later refresh
(which regenerates projects.json/crm.json FROM the store) can't resurrect a merged-away duplicate or
undo an archive. Before this fix, db_cleaner wrote the JSON directly while the store kept the old rows,
so the next refresh rolled the cleanup back."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_dbclean_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import projects_store as ps      # noqa: E402
from src.modules import crm_store as cs            # noqa: E402
from src.modules import db_cleaner                 # noqa: E402


def _proj(pid, **kw):
    base = {"id": pid, "name": pid, "participants": [], "conversation_ids": [], "key_topics": [],
            "thread_count": 0, "status": "ongoing", "ignore": False, "last_activity": "2026-06-01"}
    base.update(kw)
    return base


def _contact(email, **kw):
    base = {"email": email, "name": email, "thread_count": 0, "status": "other"}
    base.update(kw)
    return base


# ── project merge ─────────────────────────────────────────────────────────────

def test_merge_projects_persists_in_store_no_resurrection(tmp_path):
    ps.replace_from_dict(tmp_path, {"last_scan": "x", "projects": {
        "keep": _proj("keep", participants=["a@x.com"], conversation_ids=["c1"], key_topics=["t1"],
                      thread_count=2, ignore=True, last_activity="2026-06-10"),
        "dup":  _proj("dup", participants=["b@x.com"], conversation_ids=["c2"], key_topics=["t2"],
                      thread_count=3, last_activity="2026-06-20")}})

    r = db_cleaner.merge_projects(tmp_path, "keep", "dup")
    assert r["ok"] and r["removed_id"] == "dup"

    out = ps.load_projects(tmp_path)["projects"]
    assert "dup" not in out, "duplicate must be gone from the STORE (not just the JSON)"
    keep = out["keep"]
    assert set(keep["participants"]) == {"a@x.com", "b@x.com"}      # unioned
    assert set(keep["conversation_ids"]) == {"c1", "c2"}
    assert keep["thread_count"] == 5
    assert keep["last_activity"] == "2026-06-20"                     # later wins
    assert keep["ignore"] is True                                    # user column preserved

    # THE rollback test: regenerate the projection from the store (what a refresh does) →
    # the merged-away duplicate must NOT come back.
    ps.write_projection(tmp_path)
    proj = json.loads((tmp_path / "projects.json").read_text())["projects"]
    assert "dup" not in proj and "keep" in proj


def test_merge_projects_missing_returns_error(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {"keep": _proj("keep")}})
    assert db_cleaner.merge_projects(tmp_path, "keep", "ghost")["ok"] is False


# ── project archive ───────────────────────────────────────────────────────────

def test_archive_project_persists_in_store(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {"p1": _proj("p1", archived=False)}})
    r = db_cleaner.archive_record(tmp_path, "project", "p1")
    assert r["ok"]
    assert ps.load_projects(tmp_path)["projects"]["p1"]["archived"] is True
    ps.write_projection(tmp_path)                                   # survives a refresh
    assert json.loads((tmp_path / "projects.json").read_text())["projects"]["p1"]["archived"] is True
    assert db_cleaner.archive_record(tmp_path, "project", "ghost")["ok"] is False


# ── contact merge / archive (CRM had the same hole) ───────────────────────────

def test_group_contacts_keeps_both_rows(tmp_path):
    """Merge is now NON-destructive GROUPING: both rows stay, linked by group_id, one flagged primary,
    each row keeps its OWN company. (Was: the merged-away row was deleted — intentional behavior change.)"""
    cs.replace_from_dict(tmp_path, {"contacts": {
        "keep@x.com": _contact("keep@x.com", name="Jason Hao", thread_count=2, tags=["vip"], company="Acme"),
        "dup@x.com":  _contact("dup@x.com", name="Hao Jason", thread_count=3, tags=["client"], company="Globex")}})

    r = db_cleaner.merge_contacts(tmp_path, "keep@x.com", "dup@x.com")
    assert r["ok"] and r["primary_email"] == "keep@x.com"

    out = cs.load_crm(tmp_path)["contacts"]
    assert "keep@x.com" in out and "dup@x.com" in out, "both rows kept (non-destructive)"
    assert out["keep@x.com"]["group_id"] == out["dup@x.com"]["group_id"]
    assert out["keep@x.com"]["is_group_primary"] is True and out["dup@x.com"]["is_group_primary"] is False
    assert sorted(out["keep@x.com"]["tags"]) == ["client", "vip"]   # group-level union on primary
    assert "dup@x.com" in out["keep@x.com"]["aliases"]
    assert out["keep@x.com"]["company"] == "Acme"                   # each row keeps its OWN company
    assert out["dup@x.com"]["company"] == "Globex"

    cs.write_projection(tmp_path)
    proj = json.loads((tmp_path / "crm.json").read_text())["contacts"]
    assert "dup@x.com" in proj and "keep@x.com" in proj            # projection stays one-row-per-email


def test_group_contacts_user_fields_aggregate_on_primary(tmp_path):
    """Group-level user fields (tags / priority / ignore / notes) fold onto the PRIMARY losslessly."""
    cs.replace_from_dict(tmp_path, {"contacts": {
        "keep@x.com": _contact("keep@x.com", tags=["vip"], priority="low", notes="from keep"),
        "dup@x.com":  _contact("dup@x.com", tags=["client"], priority="high", notes="from dup", ignore=True)}})
    db_cleaner.merge_contacts(tmp_path, "keep@x.com", "dup@x.com")
    p = cs.load_crm(tmp_path)["contacts"]["keep@x.com"]
    assert sorted(p["tags"]) == ["client", "vip"]
    assert p["priority"] == "high" and p["ignore"] is True
    assert "from keep" in p["notes"] and "from dup" in p["notes"]


def test_merge_with_chosen_primary(tmp_path):
    """User picks which email is primary; that row is flagged + carries the group fields."""
    cs.replace_from_dict(tmp_path, {"contacts": {
        "junk@x.com": _contact("junk@x.com", tags=["a"]), "clean@x.com": _contact("clean@x.com", tags=["b"])}})
    db_cleaner.merge_contacts(tmp_path, "junk@x.com", "clean@x.com", primary_email="clean@x.com")
    out = cs.load_crm(tmp_path)["contacts"]
    assert out["clean@x.com"]["is_group_primary"] is True and out["junk@x.com"]["is_group_primary"] is False
    assert sorted(out["clean@x.com"]["tags"]) == ["a", "b"]


def test_load_crm_resolved_maps_member_to_primary(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {
        "p@x.com": _contact("p@x.com", name="Primary"), "m@x.com": _contact("m@x.com", name="Member")}})
    db_cleaner.merge_contacts(tmp_path, "p@x.com", "m@x.com")
    resolved = cs.load_crm_resolved(tmp_path)["contacts"]
    assert resolved["m@x.com"]["email"] == "p@x.com"               # member email -> primary record
    assert resolved["p@x.com"]["email"] == "p@x.com"


def test_collapse_groups_one_entry_per_group(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {
        "p@x.com": _contact("p@x.com", company="Acme", thread_count=2),
        "m@x.com": _contact("m@x.com", company="Globex", thread_count=3),
        "solo@x.com": _contact("solo@x.com")}})
    db_cleaner.merge_contacts(tmp_path, "p@x.com", "m@x.com")
    collapsed = cs.collapse_groups(tmp_path)["contacts"]
    assert "m@x.com" not in collapsed and "p@x.com" in collapsed and "solo@x.com" in collapsed
    card = collapsed["p@x.com"]
    assert sorted(card["member_emails"]) == ["m@x.com", "p@x.com"]
    assert set(card["member_companies"]) == {"Acme", "Globex"}
    assert card["thread_count"] == 5                               # summed for display


def test_get_ignored_emails_expands_group(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {"p@x.com": _contact("p@x.com"), "m@x.com": _contact("m@x.com")}})
    db_cleaner.merge_contacts(tmp_path, "p@x.com", "m@x.com")
    cs.update_contact_field(tmp_path, "p@x.com", "ignore", True)   # ignore one identity
    assert cs.get_ignored_emails(tmp_path) == {"p@x.com", "m@x.com"}  # -> ignores the whole person


def test_resolve_primary_email_returns_clean_smtp(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {
        "jason@trustedai.ca": _contact("jason@trustedai.ca"),
        "outlook_deadbeef@outlook.com": _contact("outlook_deadbeef@outlook.com")}})
    db_cleaner.merge_contacts(tmp_path, "jason@trustedai.ca", "outlook_deadbeef@outlook.com",
                              primary_email="jason@trustedai.ca")
    assert cs.resolve_primary_email(tmp_path, "outlook_deadbeef@outlook.com") == "jason@trustedai.ca"
    assert cs.resolve_primary_email(tmp_path, "stranger@x.com") == "stranger@x.com"


def test_group_survives_rebuild(tmp_path):
    """The daily rebuild (upsert_built_contacts with a fresh AI dict that has NO group fields) must
    PRESERVE group_id / is_group_primary — they're user columns, not rebuild-authority."""
    cs.replace_from_dict(tmp_path, {"contacts": {"p@x.com": _contact("p@x.com"), "m@x.com": _contact("m@x.com")}})
    db_cleaner.merge_contacts(tmp_path, "p@x.com", "m@x.com")
    gid = cs.load_crm(tmp_path)["contacts"]["p@x.com"]["group_id"]
    cs.upsert_built_contacts(tmp_path, {                            # simulate a refresh, no group fields
        "p@x.com": {"email": "p@x.com", "name": "P", "company": "NewCo", "thread_count": 9},
        "m@x.com": {"email": "m@x.com", "name": "M", "company": "NewCo2", "thread_count": 4}})
    out = cs.load_crm(tmp_path)["contacts"]
    assert out["p@x.com"].get("group_id") == gid and out["p@x.com"].get("is_group_primary") is True
    assert out["m@x.com"].get("group_id") == gid


def test_ungroup_is_reversible(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {
        "p@x.com": _contact("p@x.com", company="Acme"), "m@x.com": _contact("m@x.com", company="Globex")}})
    db_cleaner.merge_contacts(tmp_path, "p@x.com", "m@x.com")
    db_cleaner.ungroup_contact(tmp_path, "m@x.com")
    out = cs.load_crm(tmp_path)["contacts"]
    assert "m@x.com" in out and "p@x.com" in out                   # nothing deleted
    assert out["m@x.com"].get("group_id") is None                  # split out
    assert out["m@x.com"]["company"] == "Globex"                   # kept its own data


def test_find_contacts_by_name_returns_group_primary(tmp_path):
    """The draft-recipient fix end-to-end: a person grouped with a junk + a clean address resolves to
    the clean PRIMARY (deduped by group) — 'draft to <name>' never returns the proxy."""
    from src.modules import crm
    cs.replace_from_dict(tmp_path, {"contacts": {
        "jason@trustedai.ca": _contact("jason@trustedai.ca", name="Jason Hao"),
        "outlook_dead@outlook.com": _contact("outlook_dead@outlook.com", name="Jason Hao")}})
    db_cleaner.merge_contacts(tmp_path, "jason@trustedai.ca", "outlook_dead@outlook.com",
                              primary_email="jason@trustedai.ca")
    cs.write_projection(tmp_path)                          # find_contacts_by_name reads crm.json
    hits = crm.find_contacts_by_name(tmp_path, "Jason Hao")
    assert len(hits) == 1, hits                            # deduped by group
    assert hits[0]["email"] == "jason@trustedai.ca"        # the clean primary, not the proxy


def test_archive_contact_persists_in_store(tmp_path):
    cs.replace_from_dict(tmp_path, {"contacts": {"c@x.com": _contact("c@x.com", tags=["keep"])}})
    r = db_cleaner.archive_record(tmp_path, "contact", "c@x.com")
    assert r["ok"]
    c = cs.load_crm(tmp_path)["contacts"]["c@x.com"]
    assert c["archived"] is True and c["tags"] == ["keep"]          # flag set, user col preserved
    assert db_cleaner.archive_record(tmp_path, "contact", "ghost@x.com")["ok"] is False


# ── approve_candidates end-to-end (delegates to the routed functions) ─────────

def test_approve_candidates_routes_through_store(tmp_path):
    ps.replace_from_dict(tmp_path, {"projects": {
        "keep": _proj("keep", participants=["a@x.com"]),
        "dup":  _proj("dup", participants=["a@x.com"])}})
    db_cleaner.save_pending(tmp_path, [{
        "id": "cand1", "type": "project_duplicate",
        "primary": {"id": "keep"}, "duplicate": {"id": "dup"}, "confidence": "high"}])
    counts = db_cleaner.approve_candidates(tmp_path, ["cand1"])
    assert counts["merged_projects"] == 1
    assert "dup" not in ps.load_projects(tmp_path)["projects"]
