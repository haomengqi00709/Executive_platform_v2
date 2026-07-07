"""A contact value can lack its own `email` (enrichment merge with an empty base + the AI never
outputs email), and find_duplicate_contacts did `.values()` + `a["email"]` → KeyError that killed
the WHOLE weekly cleanup scan for weeks. Root-cause guards: the save chokepoint enforces the
email invariant, the reader is key-authoritative, a backfill repairs legacy rows, and run_full_scan
isolates stages so one detector's failure can't abort the rest."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_crm_inv_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules import crm_store, db_cleaner as dc  # noqa: E402


def _seed_crm(tmp_path, contacts):
    (tmp_path / "crm.json").write_text(json.dumps({"contacts": contacts}))
    crm_store.replace_from_dict(tmp_path, {"contacts": contacts})


def test_replace_from_dict_enforces_email_invariant(tmp_path):
    # a value WITHOUT email is saved → the store/projection must inject email=key
    crm_store.replace_from_dict(tmp_path, {"contacts": {
        "a@x.com": {"name": "Ann", "company": "X", "prompt_version": 3},   # no email field
    }})
    stored = json.loads((tmp_path / "crm.json").read_text())["contacts"]
    assert stored["a@x.com"]["email"] == "a@x.com"


def test_find_duplicate_contacts_survives_emailless_rows(tmp_path):
    # THE crash repro: two same-name contacts, one missing its email field → must NOT KeyError
    _seed_crm(tmp_path, {
        "ann@x.com":  {"name": "Ann Lee", "company": "X"},                 # missing email (legacy)
        "ann@y.com":  {"email": "ann@y.com", "name": "Ann Lee", "company": "Y"},
    })
    cands = dc.find_duplicate_contacts(tmp_path, ai=None)   # ai unused unless a pair reaches the judge
    assert isinstance(cands, list)                          # returned, did not raise


def test_backfill_repairs_legacy_rows(tmp_path):
    # simulate legacy data already in the store without email (bypass the invariant via raw write path)
    (tmp_path / "crm.json").write_text(json.dumps({"contacts": {
        "old@z.com": {"name": "Old", "company": "Z"}}}))
    con = crm_store._conn(tmp_path)
    con.execute("INSERT OR REPLACE INTO contacts (email, data, updated_at) VALUES (?,?,?)",
                ("old@z.com", json.dumps({"name": "Old", "company": "Z"}), "t"))   # no email
    con.commit(); con.close()
    fixed = crm_store.backfill_missing_email(tmp_path)
    assert fixed == 1
    stored = json.loads((tmp_path / "crm.json").read_text())["contacts"]
    assert stored["old@z.com"]["email"] == "old@z.com"


def test_run_full_scan_isolates_a_failing_stage(tmp_path, monkeypatch):
    # if one detector raises, the scan must still complete and keep the other stages' candidates
    _seed_crm(tmp_path, {"a@x.com": {"email": "a@x.com", "name": "A"}})
    monkeypatch.setattr(dc, "find_duplicate_contacts",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("email")))
    sentinel = [{"id": "split1", "type": "project_split", "confidence": "high",
                 "primary": {"name": "P"}, "restore": []}]
    monkeypatch.setattr(dc, "find_wrongly_merged_projects", lambda *a, **k: sentinel)
    monkeypatch.setattr(dc, "find_duplicate_projects", lambda *a, **k: [])
    monkeypatch.setattr(dc, "find_stale_records", lambda *a, **k: [])
    res = dc.run_full_scan(tmp_path, ai=None)              # must NOT raise despite the contacts stage
    ids = {c["id"] for c in res["candidates"]}
    assert "split1" in ids                                 # split stage survived the contacts crash
