"""30-prompt validation harness for the function layer (F1-F4), against REAL local data.

For each prompt: a fresh COPY of the user's local data dir, the actual bot tool the prompt should
trigger is invoked with the resolved args, and the result/store is asserted against ground truth I
pre-computed from the data. Deterministic, no Gemini, no mutation of the real data. The NL→tool
routing (which Gemini does) is spot-checked live in Teams; this proves the CODE is correct.

Run:  GTDIR="<.../ceo-local-data/cd2162aa-...>" python phase_f_test_30.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")
SRC = Path(os.environ["GTDIR"])

# ── ground truth (computed from the live local store) ───────────────────────
IPS, NEXUS = "ips-consultancy-cto-role-alignment", "nexus-capital-ai-strategy"
PROJECT_STATUS_IDS = {IPS, NEXUS}            # both active
ATTENTION_IDS = {NEXUS}                      # only early_stage/needs_attention
CMT1 = "cf70c4b89d3d291a"                    # visible commitment #1 (my_commitment)
DANIEL_BIN = "daniel.bin.zhang@ipsconsultancy.ca"
NBA = "nba@email.nba.com"
N_CONTACTS = 87
FOLLOWUP_WHO, FOLLOWUP_SUBJ = "daniel@trustai.com", "Testing"


def _fresh():
    dst = Path(tempfile.mkdtemp(prefix="gt30_")) / "d"
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("wiki", "transcripts", "*.mp4"))
    return dst


def _ctx(d, graph=None, state=None):
    return SimpleNamespace(data_dir=d, settings={"timezone": "UTC", "display_name": "Jason"},
                           state=state if state is not None else {}, owner_graph=graph,
                           graph=None, wiki_dir=d, user_model={}, user_model_path=None)


def _read(d, section):
    from src.bot_tools.sections.read_module_result.tool import build
    return json.loads(build(_ctx(d))(section))


class _CaptureGraph:
    """Fake owner Graph that records which message id open_email asked for."""
    def __init__(self): self.asked = None
    def get_message(self, mid):
        self.asked = mid
        return {"id": mid, "subject": "S", "from": {}, "toRecipients": [],
                "body": {"contentType": "text", "content": "body"}}


# ── scenarios: (category, prompt, fn(d) -> (ok, detail)) ─────────────────────
SCN = []
def scn(cat, prompt):
    def deco(fn): SCN.append((cat, prompt, fn)); return fn
    return deco


# ===== F1 — read projects from live store =====
@scn("F1", "what projects do I have")
def _(d):
    ids = {it["id"] for it in _read(d, "project_status")["items"]}
    return ids == PROJECT_STATUS_IDS, f"got {ids}, expected {PROJECT_STATUS_IDS}"

@scn("F1", "which projects need attention")
def _(d):
    ids = {it["id"] for it in _read(d, "projects_needing_attention")["items"]}
    return ids == ATTENTION_IDS, f"got {ids}, expected {ATTENTION_IDS}"

@scn("F1", "what projects do I have (a STALE results cache must be ignored)")
def _(d):
    (d / "results").mkdir(exist_ok=True)
    (d / "results" / "project_status.json").write_text(json.dumps(
        {"id": "project_status", "items": [{"id": "ghost", "name": "Ghost", "status": "ongoing"}]}))
    ids = {it["id"] for it in _read(d, "project_status")["items"]}
    return "ghost" not in ids and ids == PROJECT_STATUS_IDS, f"got {ids} (ghost must be absent)"

@scn("F1", "is the Nexus project still active / not ignored")
def _(d):
    items = _read(d, "project_status")["items"]
    nx = [it for it in items if it["id"] == NEXUS]
    return len(nx) == 1 and nx[0]["status"] == "early_stage", f"nexus={nx}"


# ===== F2 — modify project (writes the store) =====
def _modify(d, ref, field, value):
    from src.bot_tools.projects.modify_project.tool import build
    return build(_ctx(d))(ref, field, value)

def _proj(d, pid):
    from src.modules import projects_store
    return projects_store.load_projects(d)["projects"].get(pid, {})

@scn("F2", "mark the Nexus project as paused")
def _(d):
    out = _modify(d, "nexus", "status", "paused")
    return _proj(d, NEXUS).get("status") == "paused", f"{out!r}; status={_proj(d,NEXUS).get('status')}"

@scn("F2", "set the IPS project to needs_attention")
def _(d):
    _modify(d, "IPS", "status", "needs_attention")
    return _proj(d, IPS).get("status") == "needs_attention", f"status={_proj(d,IPS).get('status')}"

@scn("F2", "ignore the Nexus project (then it drops off the list)")
def _(d):
    _modify(d, "nexus", "ignore", "true")
    ig = _proj(d, NEXUS).get("ignore")
    ids = {it["id"] for it in _read(d, "project_status")["items"]}
    return ig is True and NEXUS not in ids, f"ignore={ig}, list={ids}"

@scn("F2", "un-ignore the Nexus project (resolves even though it's hidden)")
def _(d):
    _modify(d, "nexus", "ignore", "true")
    _modify(d, "nexus", "ignore", "false")
    return _proj(d, NEXUS).get("ignore") is False, f"ignore={_proj(d,NEXUS).get('ignore')}"

@scn("F2", "set the Nexus project to an INVALID status (must reject, no change)")
def _(d):
    out = _modify(d, "nexus", "status", "bogus_status")
    return "Invalid status" in out and _proj(d, NEXUS).get("status") == "early_stage", out

@scn("F2", "mark the 'Acme Onboarding' project paused (no such project → honest)")
def _(d):
    out = _modify(d, "Acme Onboarding", "status", "paused")
    return "can't match" in out.lower(), out


# ===== F3 — open original email / where-from =====
@scn("F3", "show me the full original email for commitment 1 (resolve cmt id → email_id)")
def _(d):
    from src.bot_tools.email.open_email.tool import build
    from src.modules import commitments_store as cs
    real_eid = next((c["email_id"] for c in cs.query_visible(d) if c["id"] == CMT1), None)
    g = _CaptureGraph()
    build(_ctx(d, graph=g))(CMT1)                       # bot passes the commitment id
    return g.asked == real_eid and bool(real_eid), f"open_email fetched {g.asked!r}, expected {real_eid!r}"

@scn("F3", "where is commitment 1 from (answerable from metadata, no fetch needed)")
def _(d):
    from src.modules import commitments_store as cs
    c1 = next((c for c in cs.query_visible(d) if c["id"] == CMT1), {})
    return bool(c1.get("subject")) and bool(c1.get("received")), f"subject={c1.get('subject')!r} received={c1.get('received')!r}"

@scn("F3", "open email with a clearly bad id (honest failure, no crash)")
def _(d):
    from src.bot_tools.email.open_email.tool import build
    class Boom:
        def get_message(self, mid): raise Exception("400 Bad Request")
    out = build(_ctx(d, graph=Boom()))("not-a-real-id")
    return "couldn't open" in out.lower(), out

@scn("F3", "open the email for commitment 2 (a their_commitment, id→email_id resolve)")
def _(d):
    from src.bot_tools.email.open_email.tool import build
    from src.modules import commitments_store as cs
    vis = cs.query_visible(d)
    cmt2 = vis[1] if len(vis) > 1 else {}
    g = _CaptureGraph()
    build(_ctx(d, graph=g))(cmt2.get("id", ""))
    return g.asked == cmt2.get("email_id") and bool(cmt2.get("email_id")), f"fetched {g.asked!r} vs {cmt2.get('email_id')!r}"


# ===== F4c — their_commitment auto-clear on reply =====
def _seed_their(d, cid, conv):
    from src.modules import commitments_store as cs
    cs.upsert_commitments(d, [{"id": cid, "type": "their_commitment", "description": "they owe X",
                               "conversation_id": conv, "email_id": "e-" + cid}])

@scn("F4c", "counterparty replies in a thread → their_commitment auto-clears")
def _(d):
    from src.modules import commitments_store as cs
    _seed_their(d, "tc-x", "CONV-X")
    n = cs.mark_done_by_conversation_id(d, "CONV-X")
    visible_ids = {c["id"] for c in cs.query_visible(d)}
    return n == 1 and "tc-x" not in visible_ids, f"cleared={n}, still-visible={'tc-x' in visible_ids}"

@scn("F4c", "a reply must NOT clear MY commitment in the same thread")
def _(d):
    from src.modules import commitments_store as cs
    cs.upsert_commitments(d, [{"id": "mc-x", "type": "my_commitment", "description": "I owe Y",
                               "conversation_id": "CONV-Y", "email_id": "e1"}])
    _seed_their(d, "tc-y", "CONV-Y")
    cs.mark_done_by_conversation_id(d, "CONV-Y")
    ids = {c["id"] for c in cs.query_visible(d)}
    return "mc-x" in ids and "tc-y" not in ids, f"my-kept={'mc-x' in ids}, their-cleared={'tc-y' not in ids}"

@scn("F4c", "a reply in ANOTHER thread leaves this their_commitment alone")
def _(d):
    from src.modules import commitments_store as cs
    _seed_their(d, "tc-z", "CONV-Z")
    n = cs.mark_done_by_conversation_id(d, "CONV-OTHER")
    return n == 0 and "tc-z" in {c["id"] for c in cs.query_visible(d)}, f"cleared={n}"

@scn("F4c", "existing pre-F4c their_commitments (no conv id) are unaffected by a reply")
def _(d):
    from src.modules import commitments_store as cs
    before = len([c for c in cs.query_visible(d) if c["type"] == "their_commitment"])
    cs.mark_done_by_conversation_id(d, "ANY-CONV")    # existing rows have NULL conv → no match
    after = len([c for c in cs.query_visible(d) if c["type"] == "their_commitment"])
    return before == after, f"before={before}, after={after}"


# ===== Commitments core =====
@scn("CMT", "show my commitments (visible set, my_commitment first)")
def _(d):
    from src.modules import commitments_store as cs
    vis = cs.query_visible(d)
    return len(vis) >= 1 and vis[0]["type"] == "my_commitment" and vis[0]["id"] == CMT1, \
        f"n={len(vis)}, first={vis[0]['id'] if vis else None}"

@scn("CMT", "mark commitment 1 done → drops from the visible list")
def _(d):
    from src.modules import commitments_store as cs
    before = len(cs.query_visible(d))
    cs.mark_done(d, CMT1)
    after = [c["id"] for c in cs.query_visible(d)]
    return CMT1 not in after and len(after) == before - 1, f"before={before}, after={len(after)}"

@scn("CMT", "skip (dismiss) commitment 1 → drops + stays gone")
def _(d):
    from src.modules import commitments_store as cs
    cs.mark_dismissed(d, CMT1)
    return CMT1 not in {c["id"] for c in cs.query_visible(d)}, "still visible after dismiss"

@scn("CMT", "snooze commitment 1 for 3 days → hidden now")
def _(d):
    from src.modules import commitments_store as cs
    cs.mark_snoozed(d, CMT1, days=3)
    return CMT1 not in {c["id"] for c in cs.query_visible(d)}, "still visible after snooze"

@scn("CMT", "#N resolution: 'commitment 1' resolves to the shown #1")
def _(d):
    from src.bot_tools.commitments._shared import resolve_ref
    cid, desc = resolve_ref(_ctx(d), d, "1")
    return cid == CMT1, f"resolved {cid}, expected {CMT1}"


# ===== CRM =====
@scn("CRM", "how many contacts do I have")
def _(d):
    from src.modules import crm_store
    return len(crm_store.load_crm(d)["contacts"]) == N_CONTACTS, \
        f"got {len(crm_store.load_crm(d)['contacts'])}, expected {N_CONTACTS}"

@scn("CRM", "set Daniel Bin Zhang's priority to high (other fields preserved)")
def _(d):
    from src.bot_tools.contacts.update_crm_contact.tool import build
    from src.modules import crm_store
    before = crm_store.load_crm(d)["contacts"][DANIEL_BIN]
    build(_ctx(d))(DANIEL_BIN, "priority", "high")
    after = crm_store.load_crm(d)["contacts"][DANIEL_BIN]
    return after.get("priority") == "high" and after.get("company") == before.get("company"), \
        f"priority={after.get('priority')}, company preserved={after.get('company')==before.get('company')}"

@scn("CRM", "mark NBA as ignored → it feeds the screener's ignore set")
def _(d):
    from src.bot_tools.contacts.update_crm_contact.tool import build
    from src.modules import crm_store
    build(_ctx(d))(NBA, "ignore", "true")
    return NBA in crm_store.get_ignored_emails(d), "NBA not in ignored set"

@scn("CRM", "add a note to Daniel Bin Zhang (appends, doesn't overwrite)")
def _(d):
    from src.bot_tools.contacts.update_crm_contact.tool import build
    from src.modules import crm_store
    build(_ctx(d))(DANIEL_BIN, "notes", "met at summit")
    return "met at summit" in (crm_store.load_crm(d)["contacts"][DANIEL_BIN].get("notes") or ""), "note not saved"


# ===== Email / follow-up =====
@scn("EML", "which follow-ups am I waiting on (daniel/Testing was dismissed earlier → overlay hides it)")
def _(d):
    # The cached render still lists daniel/Testing, but it was dismissed earlier this session
    # (a followup_dismissed annotation in the store). The read-time overlay must hide it → 0 shown.
    raw = json.loads((d / "results" / "followup_needed.json").read_text()).get("items", [])
    shown = _read(d, "followup_needed")["items"]
    raw_has = any(it.get("subject") == FOLLOWUP_SUBJ for it in raw)
    return raw_has and len(shown) == 0, f"raw_lists_it={raw_has}, shown={len(shown)} (overlay should hide the dismissed one)"

@scn("EML", "skip the follow up to daniel → recorded + drops off the list")
def _(d):
    from src.bot_tools.email.dismiss_email_followup.tool import build
    out = build(_ctx(d))("daniel")
    after = {it.get("subject") for it in _read(d, "followup_needed")["items"]}
    return "Dismissed 1" in out and FOLLOWUP_SUBJ not in after, f"{out!r}; remaining={after}"

@scn("EML", "do I have emails awaiting reply (reply_needed is empty in this data)")
def _(d):
    data = _read(d, "reply_needed")
    return data["count"] == 0, f"expected 0, got {data['count']}"


# ===== Tier 2 — CRM-read capability gaps =====
@scn("CRM2", "show my high-priority contacts (the live miss — now answerable)")
def _(d):
    from src.bot_tools.contacts.update_crm_contact.tool import build as upd
    from src.bot_tools.contacts.list_crm_contacts.tool import build as lst
    upd(_ctx(d))(NBA, "priority", "high")                      # set a known high-priority contact
    out = json.loads(lst(_ctx(d))(priority="high"))
    emails = {c["email"] for c in out["contacts"]}
    return NBA in emails, f"high-priority emails={emails} (expected to contain {NBA})"

@scn("CRM2", "list internal contacts (status filter on the curated CRM)")
def _(d):
    from src.bot_tools.contacts.list_crm_contacts.tool import build as lst
    out = json.loads(lst(_ctx(d))(status="internal"))
    return out["total"] == 18, f"internal total={out['total']}, expected 18"

@scn("CRM2", "list client contacts")
def _(d):
    from src.bot_tools.contacts.list_crm_contacts.tool import build as lst
    out = json.loads(lst(_ctx(d))(status="client"))
    return out["total"] == 27, f"client total={out['total']}, expected 27"

@scn("CRM2", "get_contact_history now returns the CRM profile (not just writing_style)")
def _(d):
    from src.bot_tools.contacts.update_crm_contact.tool import build as upd
    from src.bot_tools.contacts.get_contact_history.tool import build as hist
    upd(_ctx(d))(DANIEL_BIN, "priority", "high")
    out = json.loads(hist(_ctx(d))(DANIEL_BIN))
    crm = out.get("crm") or {}
    return crm.get("priority") == "high" and "company" in crm, f"crm block={crm}"

@scn("CRM2", "#N bucket separation: frequency report and CRM list don't clobber each other")
def _(d):
    from src.bot_tools.contacts.get_email_frequency_report.tool import build as freq
    from src.bot_tools.contacts.list_crm_contacts.tool import build as lst
    class FakeG:
        def get_messages(self, top=200):
            return [{"from": {"emailAddress": {"address": NBA}}, "receivedDateTime": "2026-06-23T10:00:00Z"}]
    ctx = _ctx(d, FakeG())
    freq(ctx)()                # registers "frequency_contacts"
    lst(ctx)(status="internal")  # registers "crm_contacts"
    buckets = set((ctx.state.get("_shown_lists") or {}).keys())
    return {"frequency_contacts", "crm_contacts"} <= buckets, f"buckets={buckets} (both must survive)"

@scn("CRM2", "activity report is two-way (in+out), drops noise/self, annotates CRM identity")
def _(d):
    from src.bot_tools.contacts.get_email_frequency_report.tool import build as freq
    class FakeG:
        def get_messages(self, top=200):  # inbound
            return [{"from": {"emailAddress": {"address": NBA}}, "receivedDateTime": "2026-06-23T10:00:00Z"},
                    {"from": {"emailAddress": {"address": "no-reply@teams.microsoft"}}, "receivedDateTime": "2026-06-23T10:00:00Z"},
                    {"from": {"emailAddress": {"address": "stranger@nowhere.com"}}, "receivedDateTime": "2026-06-23T10:00:00Z"}]
        def get_sent_messages_since(self, days=30, max_results=300):  # outbound
            return [{"toRecipients": [{"emailAddress": {"address": NBA}}]}]   # NBA also gets a sent → 2-way
    rows = json.loads(freq(_ctx(d, FakeG()))())
    by = {r["email"]: r for r in rows}
    noise_gone = "no-reply@teams.microsoft" not in by                # automated dropped
    nba = by.get(NBA, {})
    return (noise_gone and nba.get("in_crm") is True and nba.get("activity") == 2
            and nba.get("received") == 1 and nba.get("sent") == 1
            and by.get("stranger@nowhere.com", {}).get("in_crm") is False), \
        f"noise_gone={noise_gone}, nba={nba}"


# ── run ──────────────────────────────────────────────────────────────────────
def main():
    passed = 0
    print(f"{'#':>2} {'CAT':<4} {'RESULT':<6} PROMPT")
    print("-" * 92)
    for i, (cat, prompt, fn) in enumerate(SCN, 1):
        d = _fresh()
        try:
            ok, detail = fn(d)
        except Exception as e:
            ok, detail = False, f"EXC {type(e).__name__}: {e}"
        passed += bool(ok)
        mark = "PASS" if ok else "FAIL"
        print(f"{i:>2} {cat:<4} {mark:<6} {prompt}")
        if not ok:
            print(f"       └─ {detail}")
    print("-" * 92)
    print(f"{passed}/{len(SCN)} passed")
    return passed == len(SCN)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
