"""
Bot — Gemini function calling orchestrator.

Entry point: reply(state, text, graph, owner_graph, settings, wiki_dir, data_dir, user_model_path)
Returns: (reply_text, updated_state)
"""
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google import genai
from google.genai import types

from src.ai import DEFAULT_GEMINI_MODEL
from src.modules.db_helpers import open_sqlite
from src.modules.profile import load_profile_context, get_user_signature, append_signature_to_body
from src.modules.subject_match import normalize_subject
from src.modules.tz import now_local
from src.modules.wiki import load_index, load_meeting
from src.bot_tools.context import BotContext
from src.bot_tools import registry

MODEL        = DEFAULT_GEMINI_MODEL


def _record_bot_usage(response, feature: str, is_search: bool = False) -> None:
    """Token accounting for the bot's raw genai calls (P0) — bot bypasses AIClient."""
    try:
        from src.modules import token_usage
        um = getattr(response, "usage_metadata", None)
        if um is None:
            return
        p = getattr(um, "prompt_token_count", 0) or 0
        o = getattr(um, "candidates_token_count", 0) or 0
        t = getattr(um, "total_token_count", 0) or (p + o)
        token_usage.record(feature, "bot", p, o, t, is_search=is_search, model=MODEL)
    except Exception:
        pass


MAX_ROUNDS   = 12          # was 8; with 27 tools the model needs room to research AND act
HISTORY_LIMIT = 20
BUDGET_NUDGE_AT = 2        # rounds-remaining threshold to push the model to act instead of read
MAX_CORRECTIONS = 2        # completion gate: how many times we re-drive an unfinished action
HONEST_FALLBACK = "I looked into that but didn't finish — want me to try again?"

# ── Failed-ask carryover ─────────────────────────────────────────────────────
# A fallback turn is deliberately NOT saved to history (anti-poisoning), but HONEST_FALLBACK
# invites "try again" — so the retry arrived with its referent erased, and the model bound
# "try again" to the freshest thing in surviving history (a pushed Market Intel briefing →
# it re-ran the section). The failed ask is carried in STATE instead: recorded on fallback,
# injected into the next turn's prompt as a one-shot note, never written to history.
_FAILED_ASK_TTL = 1800   # 30 min — an old failure must not hijack a much later "try again"
_RETRY_PHRASES = ("try again", "retry", "再试", "重试", "again")


def _retryish(text: str) -> bool:
    t = (text or "").strip().lower()
    return len(t) < 30 and any(p in t for p in _RETRY_PHRASES)


def _record_failed_ask(state: dict, text: str, prev_failed: dict | None) -> None:
    """Called when a turn falls back (and is dropped from history). If THIS turn was already
    a retry ("try again"), keep the ORIGINAL ask — storing the retry phrase would be useless."""
    try:
        ask = (prev_failed or {}).get("text") if (_retryish(text) and prev_failed) else text
        if ask and ask.strip():
            state["_last_failed_ask"] = {"text": ask.strip()[:300], "ts": time.time()}
    except Exception:
        pass


def _pop_failed_ask(state: dict) -> dict | None:
    """Pop the failed-ask marker (one-shot, TTL-bounded). The caller substitutes the retry
    text DETERMINISTICALLY — a prompt note asking the model to 'understand' the note lost to
    history pull in testing (it re-answered an old topic, zero tools). Code decides, not flash."""
    try:
        failed = (state or {}).pop("_last_failed_ask", None)
    except Exception:
        return None
    if not failed or (time.time() - (failed.get("ts") or 0)) > _FAILED_ASK_TTL:
        return None
    return failed


def _effective_ask(text: str, prev_failed: dict | None) -> str:
    """What the MODEL should treat as this turn's request. A retry phrase after a failed
    (history-dropped) turn is rewritten to the original ask in code — the model never has to
    resolve the dangling reference, so it can't bind it to stale history or a pushed section."""
    if prev_failed and _retryish(text):
        return (f"{prev_failed.get('text', '')}\n"
                f"[The user said \"{(text or '').strip()}\" — RETRY the request above. The previous "
                f"attempt failed and is not shown in the history. Complete it now with tools; do not "
                f"re-run a section/briefing unless the request itself asks for that.]")
    return text

# Borrowed from Hermes (anti history-poisoning): a "fetch fresh / never answer from memory" contract.
# The flat replayed history makes the model parrot a stale answer it gave earlier (e.g. a contact list
# produced WITHOUT calling the lookup tool) instead of calling the tool again. This block forbids that.
# The "#N" carve-out preserves the CURRENT VIEWS cross-turn resolution flow (_build_current_views).
_FRESH_FETCH_CONTRACT = (
    "\n\nALWAYS FETCH FRESH — NEVER ANSWER FROM MEMORY: Contacts, emails, meetings, commitments, drafts, "
    "groups and every other stored record can change between turns. NEVER list, name, or quote any such "
    "record from your own memory or from anything said EARLIER in this conversation — earlier turns (and any "
    "list, contact, email or result they contain) are REFERENCE ONLY and may be stale; they do NOT replace "
    "calling the tool. To answer 'who is X', 'find X's email', 'draft to X', or 'show my emails / meetings / "
    "commitments', you MUST call the matching lookup tool THIS turn (find_contacts_by_name, get_recent_emails, "
    "get_upcoming_meetings, read_module_result, …) and answer ONLY from that fresh result — even if you "
    "believe you already know it from earlier in the chat. If information is missing, use the lookup tool; ask "
    "the user ONLY when no tool can retrieve it. Do NOT repeat or re-send an answer you gave in an earlier turn "
    "(a contact list, an email, a result) — if the user asks again, RE-FETCH with the tool. The user's LATEST "
    "message is the only thing to act on. The ONE exception: resolving a '#N' reference against the CURRENT "
    "VIEWS block below is allowed — those ids are carried forward for exactly that purpose."
)

# Tools that DO something (mutate state / create a resource) vs. read tools. Mirrors the
# Action-tool telemetry set. Every tool now lives in src/bot_tools/<domain>/<tool>/ and
# declares `action: true` in its tool.md; the registry returns the action names, so this
# inline set is empty. (Kept so the loop's `set(ACTION_TOOLS) | _reg_actions` still works.)
ACTION_TOOLS = frozenset()


def _notify_owner(owner_uid: str, message: str) -> None:
    """Push a Teams DM to the owner from a background bot thread. Deferred import
    of the server helper mirrors run_skill's pattern (server imports bot, so a
    module-load import would be circular). _notify_owner_teams resolves the
    chat_id itself, so only owner_uid is needed."""
    try:
        if owner_uid:
            from src.server import _notify_owner_teams
            _notify_owner_teams(owner_uid, message)
    except Exception as e:
        print(f"[Bot] notify failed: {e}")


def _with_indices(items: list[dict]) -> list[dict]:
    """Prefix each item with a 1-based `index` field. Single source of truth
    for the [#N] convention all list-returning tools share — the AI displays
    items as `[#N] …` and resolves user's later `#N` references against the
    canonical IDs (email_id / event_id / draft_id / …) on each item."""
    return [{"index": i + 1, **(it or {})} for i, it in enumerate(items or [])]


def _register_list(ctx, list_type: str, items: list[dict], id_field: str,
                   label_fn=None, source: str = None) -> None:
    """Persist the list the bot just showed into ctx.state['_shown_lists'][list_type].

    The [#N] convention only survives within the live turn — chat history is stored as
    plain text (see _save_turn), so a list shown a few turns ago (or a pushed briefing)
    loses its canonical ids and "#N" becomes unresolvable. This keeps {pos, id, label}
    in the per-conversation state (persisted to teams_bot.json), so _build_current_views
    can replay it next turn. `pos` mirrors the displayed [#N]; the bucket is replaced
    wholesale and bounded. Best-effort: never raises into a tool."""
    try:
        if ctx is None or not items:
            return
        state = getattr(ctx, "state", None)
        if state is None:
            return
        reg = []
        for i, it in enumerate(items[:15]):
            if not isinstance(it, dict):
                continue
            try:
                label = (label_fn(it) if label_fn else "")[:80]
            except Exception:
                label = ""
            reg.append({"pos": i + 1, "id": it.get(id_field), "label": label})
        if not reg:
            return
        state.setdefault("_shown_lists", {})[list_type] = {
            "ts": time.time(),
            "source": source or list_type,
            "id_field": id_field,
            "items": reg,
        }
    except Exception:
        pass


def _build_current_views(state: dict) -> str:
    """Compact snapshot of state['_shown_lists'] for the system prompt, so the model can
    resolve "#N" against lists shown in PRIOR turns (history is text-only and drops ids).
    Drops buckets older than 24h and caps size hard. Returns '' when nothing to show."""
    try:
        shown = (state or {}).get("_shown_lists") or {}
        if not shown:
            return ""
        now = time.time()
        blocks = []
        for typ, bucket in list(shown.items())[:6]:
            if not isinstance(bucket, dict) or now - float(bucket.get("ts") or 0) > 86400:
                continue
            items = bucket.get("items") or []
            if not items:
                continue
            parts = []
            for it in items[:15]:
                idv = it.get("id")
                lbl = (it.get("label") or "")[:60]
                parts.append(f'{it.get("pos")}={idv} "{lbl}"' if idv else f'{it.get("pos")}. "{lbl}"')
            src = bucket.get("source")
            head = f"  {typ}" + (f" (from {src})" if src and src != typ else "") + ": "
            blocks.append(head + "; ".join(parts))
        if not blocks:
            return ""
        return (
            "\n\nCURRENT VIEWS (lists already shown to the user in earlier turns — the canonical "
            "ids are kept here because chat history only stores plain text). To act on a \"#N\", "
            "resolve it against the bucket whose TYPE matches the action, read that item's id, and "
            "pass it to the action tool; never retype names:\n" + "\n".join(blocks)
        )
    except Exception:
        return ""


# When an action MUTATES a domain, the list the user saw for that domain is now stale — a later
# "#N" against it would resolve to the wrong row (e.g. mark #1 done, then "snooze 2" hits the OLD #2).
# So after a successful action we drop its domain's _shown_lists bucket(s); the next "#N" then has no
# stale bucket to match and re-resolves against the LIVE store (or forces a fresh read).
_ACTION_INVALIDATES = {
    "mark_commitment_done":   ("commitments",),
    "snooze_commitment":      ("commitments",),
    "dismiss_commitment":     ("commitments",),
    "modify_project":         ("projects",),
    "update_crm_contact":     ("contacts", "crm_contacts", "frequency_contacts"),
    "tag_contact":            ("contacts", "crm_contacts", "frequency_contacts"),
    "tag_recent_contacts":    ("contacts", "crm_contacts", "frequency_contacts"),
    "dismiss_email_followup": ("emails",),
    "approve_draft":          ("emails",),
}


def _invalidate_shown_lists(state: dict, tool_name: str) -> None:
    """Drop the stale _shown_lists buckets a successful action invalidated. Best-effort."""
    try:
        buckets = (state or {}).get("_shown_lists")
        if not buckets:
            return
        for t in _ACTION_INVALIDATES.get(tool_name, ()):
            buckets.pop(t, None)
    except Exception:
        pass


# A line that is part of a rendered list (bullet, "[#N]", "N.", or a priority emoji) — used to
# split a reply's prose preamble from its list body.
_LIST_LINE_RE = re.compile(r"^\s*(\[#?\d+\]|#\d+|\d+[.)]|[•*]|-\s|🔴|🟡|🟢|⚠️|📌|📅|📆)")

# Lightweight signal that the user asked to SEE a list (so an under-listed reply should be
# completed even if the model wrote no bullets). Multilingual; permissive on purpose — a false
# positive only appends the full canonical list, which is never wrong, just verbose.
_DISPLAY_HINTS = (
    "show", "list", "display", "what's my", "whats my", "what are my", "what is my",
    "give me", "all my", "everything", "my commitment", "my task", "my action",
    "my email", "my to-do", "my todo", "my follow", "outstanding", "pending",
    "显示", "列出", "列一下", "看一下", "看下", "有哪些", "我的", "全部", "所有", "待办", "承诺", "任务",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_CONTACT_LEADIN = ("i found these contacts", "here are the contacts", "found these contacts for",
                   "contacts named", "i found a few")


def _is_poisoned_turn(final_text: str, tools_called: list) -> bool:
    """True when a reply PRESENTS a stored-record listing (a contact list / a multi-line [#N] list / an
    email address) but NO tool ran at all this turn — i.e. it was produced from memory or replayed
    history, not a fresh call. Such a turn must NOT be persisted: stored flat and replayed, it teaches
    the model to parrot the stale answer instead of calling the lookup tool (the live "draft to jason →
    backed a stale ips/proxy list, tools=[]" bug). Conjunction + tight signals so a plain answer
    (greeting, decline, explanation) — or any turn where a real tool ran — is NEVER dropped."""
    if tools_called:
        return False                                    # a real call ran → the content is genuine, keep it
    ft = final_text or ""
    if _EMAIL_RE.search(ft):
        return True                                     # an email address with no fetch behind it = the artifact
    if any(s in ft.lower() for s in _CONTACT_LEADIN):
        return True
    return sum(1 for ln in ft.splitlines() if _LIST_LINE_RE.match(ln)) >= 2   # ≥2 list lines = a listed set


def _enforce_list_completeness(text: str, state: dict, user_text: str) -> str:
    """Approaches 1+3 for list display. read_module_result stashes the deterministic full render
    of any list section it read (identical to the Teams briefing) into state['_pending_render'].
    Here, if the model's own reply omits items it should have listed — it enumerated only a subset,
    OR the user asked to see the list and the model under-showed — we substitute the canonical
    block so a commitment/email/etc. is never silently dropped. A reply that already lists every
    item, or a non-list (analytical) answer, is left untouched."""
    try:
        pend = state.pop("_pending_render", None) if isinstance(state, dict) else None
        if not pend:
            return text
        block  = (pend.get("block") or "").strip()
        labels = pend.get("labels") or []
        count  = int(pend.get("count") or 0)
        if not block or count <= 0 or not labels:
            return text
        low = (text or "").lower()
        present = sum(1 for lbl in labels if lbl and lbl in low)
        has_list_lines = any(_LIST_LINE_RE.match(ln) for ln in (text or "").splitlines())
        is_display = any(h in (user_text or "").lower() for h in _DISPLAY_HINTS)
        truncated = (has_list_lines and 1 <= present < count) or (is_display and present < count)
        if not truncated:
            return text
        # Keep any non-list preamble the model wrote, then append the full canonical list.
        preamble_lines = []
        for ln in (text or "").splitlines():
            if _LIST_LINE_RE.match(ln):
                break
            preamble_lines.append(ln)
        preamble = "\n".join(preamble_lines).strip()
        print(f"[Bot] list-completeness guard: model showed {present}/{count} "
              f"{pend.get('section_id')} item(s) — substituting canonical render")
        return (preamble + "\n\n" + block).strip() if preamble else block
    except Exception:
        return text


SECTION_IDS = {
    "ai_summary":           "Morning Briefing — daily summary of calendar, emails, priorities, and key relationships",
    "market_intelligence":  "Market Intelligence — current industry news, competitor updates, market trends",
    "company_intelligence": "Company Intelligence — targeted signals on companies you've flagged for monitoring (LinkedIn, X, news)",
    "reply_needed":         "Emails Awaiting Reply — inbox emails where the sender is waiting for your response",
    "followup_needed":      "Sent — No Response — emails YOU sent that the other party hasn't replied to yet",
    "commitments_extract":  "Commitments Extracted — all promises and deadlines found in emails (yours and others')",
    "upcoming_commitments": "Upcoming Commitments — forward-looking view of deadlines and commitments in the next 2 weeks",
    "recent_meetings":      "Recent Meetings — summaries and decisions from recorded meetings",
    "meeting_action_items": "Meeting Action Items — open action items extracted from meeting recordings",
    "relationship_health":  "Relationship Health — health scores and alerts for key business contacts",
    "business_insights":    "Business Insights — AI-generated analysis of business patterns and opportunities",
    "expenses":             "Document Capture — receipts (→ Excel), invoices, and contracts from email attachments",
    "email_monitor":        "Email Monitor Triage — custom rules for classifying incoming emails as priority, review, or skip",
    "project_status":              "Project Status — portfolio view of all active projects with status and momentum",
    "projects_needing_attention":  "Projects Needing Attention — projects flagged as needs_attention or early_stage",
    "meetings_today":              "Today's Meetings — calendar view of meetings scheduled for today",
    "due_today":                   "Due Today — commitments the user owes today",
    "yesterday_recap":             "Yesterday's Recap — emails, meetings, and commitments from yesterday",
    "meeting_prep":                "Meeting Prep — pre-meeting context auto-fired ~30 min before each meeting",
}


_GENAI_CLIENT = None
_GENAI_LOCK = __import__("threading").Lock()


def _client() -> genai.Client:
    """A single shared genai client for the whole process. Was: a fresh genai.Client() per call —
    but the google-genai SDK shares an underlying httpx transport across Client instances, so when a
    SECOND client coexists with the first (e.g. search_web creating its own while a reply turn already
    holds one) and either is GC'd, the shared transport closes and the other fails with 'Cannot send a
    request, as the client has been closed' (live: search_web errored mid-turn). One cached client
    avoids the multi-instance close race."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        with _GENAI_LOCK:
            if _GENAI_CLIENT is None:
                _GENAI_CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _GENAI_CLIENT


# ── Conversation history ───────────────────────────────────

def _load_history(db_path: Path, limit: int = HISTORY_LIMIT) -> list:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = open_sqlite(db_path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS history "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, ts REAL)"
    )
    con.commit()
    rows = con.execute(
        "SELECT role, content FROM history ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    rows.reverse()
    return [
        types.Content(role=role, parts=[types.Part(text=content)])
        for role, content in rows
    ]


def _save_turn(db_path: Path, user_text: str, assistant_text: str):
    con = open_sqlite(db_path)
    ts = time.time()
    con.execute("INSERT INTO history (role, content, ts) VALUES (?, ?, ?)", ("user",  user_text,       ts))
    con.execute("INSERT INTO history (role, content, ts) VALUES (?, ?, ?)", ("model", assistant_text,  ts + 0.001))
    con.commit()
    con.close()


# ── User Model (persistent structured preferences) ─────────

def _load_user_model(path: Path) -> dict:
    if path and path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_user_model(path: Path, model: dict):
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    model["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Atomic write — see src/server.py:_write_json for context
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(model, indent=2, ensure_ascii=False))
    import os
    os.replace(tmp, path)


def _build_session_context(data_dir: Path) -> str:
    """Read cached section results and return a short status summary for the system prompt.
    Zero API cost — silently skips any missing or malformed files."""
    lines = []
    try:
        d = json.loads((data_dir / "results" / "reply_needed.json").read_text())
        items = d.get("items", [])
        if items:
            oldest = items[0]
            lines.append(
                f"Reply needed: {len(items)} emails"
                f" — oldest: \"{oldest.get('subject','')}\" from {oldest.get('from_name', oldest.get('from_email',''))} ({oldest.get('days_waiting',0)}d)"
            )
    except Exception:
        pass
    try:
        d = json.loads((data_dir / "results" / "followup_needed.json").read_text())
        items = d.get("items", [])
        if items:
            lines.append(f"Follow-up needed: {len(items)} sent emails with no response")
    except Exception:
        pass
    try:
        d = json.loads((data_dir / "results" / "meeting_action_items.json").read_text())
        open_items = [a for a in d.get("items", []) if not a.get("completed")]
        if open_items:
            lines.append(f"Open meeting action items: {len(open_items)} unresolved")
    except Exception:
        pass
    try:
        d = json.loads((data_dir / "results" / "relationship_health.json").read_text())
        at_risk = [h for h in d.get("items", []) if h.get("status") in ("at_risk", "dormant")][:3]
        if at_risk:
            names = ", ".join(h.get("name") or h.get("email", "") for h in at_risk)
            lines.append(f"Relationship alerts: {names}")
    except Exception:
        pass
    try:
        from src.modules import email_store
        d = email_store.get_poller_state(data_dir)
        notified = (d.get("last_notified_emails") or [])[-5:]
        if notified:
            items = "; ".join(
                f'"{e["subject"]}" from {e["from"]}' for e in notified
            )
            lines.append(f"Recently notified emails (last {len(notified)}): {items}")
    except Exception:
        pass
    if not lines:
        return ""
    return "Current status (from last run):\n" + "\n".join(f"• {l}" for l in lines)


# ── Core reply function ────────────────────────────────────

def reply(
    state: dict,
    text: str,
    graph,
    owner_graph,
    settings: dict,
    wiki_dir: Path,
    data_dir: Path,
    user_model_path: Path = None,
) -> tuple[str, dict]:
    db_path    = data_dir / "bot_history.db"
    history    = _load_history(db_path)
    user_model = _load_user_model(user_model_path)

    # Migrated tools live in src/bot_tools/<domain>/<tool>/ and bind to a context
    # sharing this turn's mutable `state`. Tools still defined inline below are merged
    # with these in `all_tools`; their routing lines are appended to TOOL ROUTING.
    _ctx = BotContext(state=state, owner_graph=owner_graph, graph=graph,
                      settings=settings, data_dir=data_dir, wiki_dir=wiki_dir,
                      user_model=user_model, user_model_path=user_model_path)
    _reg_tools, _reg_actions, _reg_routing = registry.build(_ctx)

    # ── System prompt ──────────────────────────────────────
    display_name     = settings.get("display_name", "the executive")
    business_context  = load_profile_context(data_dir)
    writing_style     = settings.get("writing_style_note", "").strip()
    timezone_str      = settings.get("timezone", "UTC")
    now_str           = now_local(data_dir).strftime("%A, %B %d, %Y %H:%M %Z")
    bc_line           = f"\n\nBusiness context: {business_context}" if business_context else ""
    style_line        = (
        f"\n\nWriting style for all email drafts:\n{writing_style}"
        f"\nIf get_contact_history returns a writing_style_note for a specific contact, use that instead — it takes priority over the global style above."
    ) if writing_style else ""

    # Inject user model state — AI answers config questions without tool calls
    ignored  = user_model.get("ignored_senders", [])
    rules    = user_model.get("behavioral_rules", [])
    user_ctx = ""
    if ignored or rules:
        user_ctx = "\n\nUser preferences (already configured):\n"
        if ignored:
            user_ctx += f"- Ignored senders: {', '.join(ignored)}\n"
        if rules:
            user_ctx += "- Behavioral rules:\n" + "".join(f"  • {r}\n" for r in rules)

    # Zero-cost session status from cached module results
    session_ctx = ""
    if data_dir:
        session_ctx = _build_session_context(data_dir)
    if session_ctx:
        session_ctx = f"\n\n{session_ctx}"

    # Cross-turn addressing: replay lists shown in prior turns (history is text-only).
    current_views = _build_current_views(state)

    pending_note = ""
    # One-shot failed-ask carryover: the previous turn failed and was dropped from history
    # (anti-poisoning), so a bare "try again" would dangle. _effective_ask rewrites it to the
    # original request in CODE; _prev_failed is threaded to _record_failed_ask so a failing
    # retry chain keeps pointing at the original request.
    _prev_failed = _pop_failed_ask(state)
    pending_draft   = state.get("pending_draft")
    pending_expense = state.get("pending_expense")
    pending_queue   = state.get("pending_queue") or []

    if pending_draft:
        subj  = pending_draft.get("subject", "")
        to    = pending_draft.get("to", "")
        extra = f" ({len(pending_queue)} more in queue)" if pending_queue else ""
        pending_note += (
            f"\n\n⚠️ STAGED EMAIL DRAFT (shown to the user, NOT saved yet) — Subject: '{subj}', To: {to}{extra}. "
            f"Decide what the user's message means for THIS draft:\n"
            f"  • Save it ('1' / 'save' / 'yes' / 'looks good' / 'save it') → call approve_draft() to save it to Outlook Drafts.\n"
            f"  • Revise it ('make it warmer', 'add …', 'shorter', 'change the subject') → call create_reply_draft() AGAIN "
            f"with the updated subject/body to re-stage, then show the new version. Never say you 'can't edit a saved draft' — just re-compose.\n"
            f"  • Discard it ('no' / 'skip' / 'discard' / 'cancel') → call skip_draft().\n"
            f"  • If they change topic or reference item numbers from a different list, they are NOT acting on the draft — handle that instead."
        )

    if pending_expense:
        _pit   = pending_expense.get("item", {})
        vendor = _pit.get("vendor") or _pit.get("counterparty") or "?"
        amount = _pit.get("amount", "?")
        pending_note += (
            f"\n\n⚠️ PENDING EXPENSE DUPLICATE — {vendor} {amount}. "
            f"If the user says YES → call confirm_expense(). "
            f"If they say NO → call discard_expense()."
        )

    pending_file = state.get("pending_file")
    if pending_file:
        _fn  = pending_file.get("filename", "a file")
        _dt  = pending_file.get("doc_type", "file")
        _sum = pending_file.get("summary") or ""
        _saved = " as an expense" if _dt in ("receipt", "invoice", "contract") else ""
        pending_note += (
            f"\n\n📎 A FILE THE USER JUST SENT is available: '{_fn}' ({_dt})"
            f"{(' — ' + _sum) if _sum else ''}. It has already been saved{_saved}. "
            f"If the user asks to send / forward / email / attach this file to someone (e.g. 'send this "
            f"to Bob', 'forward it to accounting') → call forward_file(to=<recipient email or name>). Do "
            f"NOT ask them to resend the file — you already have it. If they ask what it says, use the summary."
        )

    pending_group = state.get("pending_group_email")
    if pending_group:
        gtag = pending_group.get("tag", "")
        gn   = len(pending_group.get("emails") or [])
        pending_note += (
            f"\n\n⚠️ STAGED GROUP EMAIL — about '{pending_group.get('intent','')}' to {gn} "
            f"people in group '{gtag}'. If the user agrees (go ahead / yes / do it / create them) "
            f"→ call confirm_group_email(). If they back out (cancel / no / never mind) → call "
            f"cancel_group_email(). confirm_group_email only DRAFTS (never auto-sends); if the user "
            f"says 'send them', still call confirm_group_email, then tell them the drafts are in "
            f"Outlook to review and send from there."
        )

    system = (
        f"You are an AI executive assistant for {display_name}.{bc_line}{style_line}\n\n"
        f"CURRENT DATE & TIME (authoritative): {now_str} [{timezone_str}].\n"
        f"  This is the ONLY source of truth for 'today', 'tomorrow', 'this week', deadlines, etc.\n"
        f"  IGNORE any date written in EARLIER messages of this conversation — they reflect when\n"
        f"  those messages were sent and are likely stale. Always compute a relative day\n"
        f"  (today/tomorrow/this Friday) from the CURRENT DATE above, never from older messages.\n"
        f"Be concise, professional, action-oriented. Use bullet points for lists.\n"
        f"Never invent data. Respond in the same language the user writes in.\n\n"
        f"LIST FORMATTING (important):\n"
        f"  When a tool returns a list (emails, meetings, contacts, drafts, action items, etc.),\n"
        f"  display each item prefixed with [#N] starting at 1, e.g.:\n"
        f"    [#1] Sarah Chen — \"Q3 budget question\" (2 days ago)\n"
        f"    [#2] Bob Smith — \"Renewal notice\"\n"
        f"  Tool outputs already include an `index` field and a canonical ID\n"
        f"  (email_id / event_id / draft_id / id / etc.) on each item.\n\n"
        f"  When the user later says \"#N\", \"number N\", or just \"N\" referring to a list,\n"
        f"  resolve it against the list whose TYPE matches the action — NOT simply whatever\n"
        f"  list was shown most recently:\n"
        f"    - snooze/skip/dismiss/mark/done N  → a COMMITMENTS list\n"
        f"    - reply to / draft N               → an EMAIL list\n"
        f"    - meeting N / who's in N           → a MEETINGS list\n"
        f"    - schedule with / contact N        → a CONTACTS list\n"
        f"  The number means the item at THAT position in the list the user is looking at — i.e.\n"
        f"  (1) the CURRENT VIEWS block below, then (2) a list visible in this conversation. Pass\n"
        f"  the item's canonical id (commitments: its `id`) to the action tool; NEVER retype names.\n"
        f"  If you have NOT shown the matching list in THIS conversation (e.g. the user is acting\n"
        f"  on a pushed briefing), you MUST call read_module_result FIRST — a cheap, SYNCHRONOUS\n"
        f"  read of the EXISTING snapshot (NOT run_skill, NOT a refresh) — BEFORE any\n"
        f"  mark/snooze/dismiss, so the numbers line up with what the user actually saw. Pick the\n"
        f"  section the user named: 'due today N' → due_today; 'upcoming N' → upcoming_commitments;\n"
        f"  otherwise commitments_extract. Do NOT call a commitment tool with a bare number before\n"
        f"  that read.\n"
        f"  If you STILL cannot match N, do NOT run a section, do NOT say you are 'waiting' for\n"
        f"  anything to refresh, and do NOT claim it is done. Reply honestly: \"I can't match #N\n"
        f"  to your current list — here's what I have:\" and list that view (or say it's empty).\n"
        f"  Asking the user which item is a COMPLETE answer, not a failure.\n\n"
        f"DISAMBIGUATION — LOOK BEFORE YOU ASK:\n"
        f"  When the user names a person/target for an action (schedule a meeting, draft, email\n"
        f"  someone) and you don't already have the exact one, you must LOOK FIRST — call the\n"
        f"  relevant lookup tool (find_contacts_by_name for people) BEFORE asking anything. Then:\n"
        f"    - exactly one match  → proceed with it, don't ask.\n"
        f"    - several matches    → show them as a [#N] list (name — company — email) and ask\n"
        f"      which one; the user picks by number. NEVER reply a vague 'I found a few named X,\n"
        f"      please specify' WITHOUT first looking them up and listing them.\n"
        f"    - no match           → say so and ask for the email.\n\n"
        f"ACT, DON'T ASK (when you can reasonably proceed):\n"
        f"  - Drafting an email: if you know the recipient and the gist, COMPOSE your best draft\n"
        f"    NOW from context (the email thread, the user's writing style, the stated intent) and\n"
        f"    stage it — drafts are shown for review and are fully editable, so asking 'what should\n"
        f"    it say?' is unnecessary and unwanted. Only ask if you genuinely don't know WHO it\n"
        f"    goes to. 'draft a reply to X's email' → draft it; don't ask for the body.\n"
        f"  - Scheduling a SOLO block (no other attendees) with a vague time: pick a sensible\n"
        f"    default (morning→09:00, afternoon→14:00, 30 min unless stated; nearest matching day),\n"
        f"    CREATE it, and tell the user the slot so they can move it. Don't ask for a time you\n"
        f"    can reasonably default.\n"
        f"  - Scheduling a meeting WITH other attendees and a vague time: do NOT guess-and-invite.\n"
        f"    PROPOSE a specific slot ('I'll set it for Mon 9:00–9:30 with X — sound good?') and\n"
        f"    create it only after the user confirms, so a real invite never goes out at a guessed\n"
        f"    time. If the time is already specific, just create it.\n"
        f"  - In general prefer doing-then-showing over interrogating; the user can correct you.\n\n"
        f"MULTIPLE REQUESTS IN ONE MESSAGE:\n"
        f"  If the user asks for more than one thing ('do X and also Y', 'A and B'), handle ALL of\n"
        f"  them THIS turn — call each needed tool in sequence — then give one combined reply.\n"
        f"  Never address only the first and silently drop the rest. If one part needs the user,\n"
        f"  do the parts you can and clearly state what is still pending.\n\n"
        f"WHEN YOU CAN'T DO SOMETHING:\n"
        f"  If the user asks for an action you have NO tool for (cancel or reschedule a calendar\n"
        f"  event, forward or delete an email, set out-of-office, send a text, filter a group by\n"
        f"  role), say plainly you can't, and offer the closest thing you CAN do (e.g. 'I can't\n"
        f"  move calendar events, but I can draft a reschedule note'; 'I can't filter by role —\n"
        f"  here are the members, tell me who to include'). NEVER fake success or claim you did\n"
        f"  something you didn't — creating a NEW event is not 'moving' an existing one.\n\n"
        f"TOOL ROUTING:\n"
        f"  get_recent_emails          → 'show my emails', 'what did X send', 'unread messages'\n"
        f"  get_upcoming_meetings      → FUTURE meetings only: 'what meetings do I have', 'who is in my next call', 'meetings today/tomorrow'.\n"
        f"                               For a PAST meeting ('my last meeting', 'what did we decide', 'recap') use get_meeting_summary or read_module_result(recent_meetings) — NOT this.\n"
        f"  get_contact_history        → 'history with X', 'last email from John'\n"
        f"  find_contacts_by_name      → resolve a NAME → contact/email ('who is Daniel', 'email for Tingcheng'). Call this FIRST whenever the user names someone for an action and you don't have their email — see DISAMBIGUATION above: one match → proceed, several → list as [#N] and ask, never ask blindly\n"
        f"  get_email_frequency_report → 'who do I email most', 'most active contacts'\n"
        f"  read_module_result         → 'what did the briefing say', 'show last email analysis'. Section by intent:\n"
        f"                               • 'what's on my plate', 'my to-dos / tasks', 'what do I need to do', 'my open items' → commitments_extract (ALL open commitments — NOT due_today, which is only items owed TODAY and is usually empty)\n"
        f"                               • 'what am I waiting on from others', 'who owes me', 'what are people getting back to me on' → commitments_extract (it INCLUDES their_commitments)\n"
        f"                               • 'what's due today' → due_today\n"
        f"                               • 'emails I still need to reply to' → reply_needed;  'emails I'm waiting to hear back on' (MY sent mail) → followup_needed\n"
        f"  check_email_handling       → 'did I reply to Sarah?', 'what happened with the Acme email?', 'has the X thread been handled?'\n"
        f"                               Reports whether the email is still open or already handled (replied / drafted / subject_match / meeting).\n"
        f"  get_meeting_summary        → 'what did we decide in the Q3 meeting?', 'summarize my meeting with John', 'recap last week's sync', 'what did we decide in my last/recent meeting?'\n"
        f"                               After check_email_handling returns kind=meeting, call this with the target_id or target_subject to fetch the recap.\n"
        f"  search_web                 → 'news about X', 'industry trends' (NOT own inbox/calendar)\n"
        f"  read_settings              → 'what are my settings', 'show my ignore list'\n"
        f"  update_setting             → 'ignore emails from X', 'add rule Y'\n"
        f"  read_skill_instruction     → 'how is X configured', 'show instructions for X'\n"
        f"  update_skill_instruction   → 'don't show X', 'skip Y in followup', 'stop showing newsletters in reply_needed',\n"
        f"                               'ignore this email in future briefings', 'change how Z works'.\n"
        f"                               Always pair with section_id. First read_skill_instruction, then append new rule.\n"
        f"                               After updating, call run_skill(section_id) so changes take effect immediately.\n"
        f"  run_skill                  → 'run morning briefing now', 'refresh my emails section'\n"
        f"  create_reply_draft         → 'draft a reply to X', 'write an email to Y', 'compose a response'\n"
        f"                               The target email is usually ALREADY in your context (the Reply-needed\n"
        f"                               list, your most recent get_recent_emails output, or a pending draft shown\n"
        f"                               above) — use it directly. Call AT MOST one read tool to find the email if\n"
        f"                               it isn't already visible, then compose the full body and save. Do NOT chain\n"
        f"                               several read tools before drafting. Draft saves immediately — no approval.\n"
        f"  approve_draft / skip_draft → only when a pending draft is shown above\n"
        f"  update_crm_contact         → 'mark X as high priority', 'add note to Sarah', 'set company for John'\n"
        f"  create_calendar_event      → 'schedule meeting with X', 'block my calendar Friday', 'create Teams call'\n"
        f"                               Pass `day` as the word the user used (today/tomorrow/friday/YYYY-MM-DD); the\n"
        f"                               system computes the real date — never do the date arithmetic yourself.\n"
        f"  run_outreach               → 'draft outreach for the people I met at X', 'batch email contacts from OneDrive folder', 'draft outreach for everyone tagged Y'\n"
        f"                               Three modes (pick one): folder= (OneDrive), tag= (CRM by tag), recent_hours= (CRM by recency)\n"
        f"  list_my_groups / list_group_members → 'what groups do I have?', 'who's in the Investors group?'\n"
        f"  draft_group_email          → 'email the X group about Y', 'draft an email to everyone in the X group', 'message everyone tagged X about Y', 'write the Investors group about Z' — personalized per contact, draft-only; stages first, then confirm_group_email after the user agrees\n"
        f"  tag_recent_contacts        → 'tag everyone I just added as X', 'group these contacts as Calgary Summit 2026'\n\n"
        + "".join(_reg_routing)
        + f"AVAILABLE SECTIONS (use these exact section_id values for run_skill, "
        f"read_skill_instruction, update_skill_instruction):\n"
        + "".join(
            f"  {sid:30s} → {desc.split(' — ', 1)[1] if ' — ' in desc else desc}\n"
            for sid, desc in SECTION_IDS.items()
        )
        + (
            f"\nHONESTY RULE: When a tool returns an error or an unexpected result, "
            f"REPORT IT honestly to the user. Do NOT reply 'Done' or pretend success "
            f"when the tool failed. Show what went wrong and what you did/didn't do. "
            f"If you did NOT successfully call the action tool the user asked for "
            f"(create_reply_draft / create_calendar_event / update_crm_contact / etc.), do NOT "
            f"claim you performed the action — say it is not done yet. "
            f"But when you decline an action because an index or target genuinely can't be matched, "
            f"that honest decline IS the complete answer — do NOT retry it as an unfinished action "
            f"and do NOT tell the user you are waiting for data to refresh."
        )
        + _FRESH_FETCH_CONTRACT
        + f"{user_ctx}"
        + f"{session_ctx}"
        + f"{current_views}"
        + f"{pending_note}"
    )

    all_tools = list(_reg_tools)   # every tool now lives in src/bot_tools/<domain>/<tool>/

    # ── Gemini function calling loop ───────────────────────
    client   = _client()
    # The model sees the EFFECTIVE ask ("try again" → the failed original, resolved in code);
    # history keeps the user's literal words (_save_turn below uses `text`).
    effective_text = _effective_ask(text, _prev_failed)
    contents = list(history) + [types.Content(role="user", parts=[types.Part(text=effective_text)])]
    fn_map   = {f.__name__: f for f in all_tools}
    _action_set = set(ACTION_TOOLS) | _reg_actions   # inline frozenset + migrated tools

    final_text     = ""
    tools_called   = []
    action_results = {}          # action tool name -> succeeded at least once this turn
    finish_mode    = "normal"    # normal | redrive | needs_user | exhausted | fallback
    total_rounds   = 0

    def _run_agent_rounds(max_rounds: int) -> str:
        """Run the function-calling loop until the model returns a text answer (no tool call)
        or the round budget runs out. Mutates tools_called / action_results / contents in place.
        Returns the model's final text ('' if it never produced one)."""
        nonlocal total_rounds
        for _j in range(max_rounds):
            total_rounds += 1
            # Gemini intermittently returns an empty candidate (out=0, no parts) under load.
            # Retry a few times before treating it as 'no output', so a transient blank doesn't
            # surface to the user as a hollow "I looked into that but didn't finish" fallback.
            parts = []
            for _attempt in range(3):
                response = client.models.generate_content(
                    model   = MODEL,
                    contents= contents,
                    config  = types.GenerateContentConfig(
                        system_instruction = system,
                        tools              = all_tools,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                _record_bot_usage(response, "bot")
                candidate = response.candidates[0] if response.candidates else None
                parts     = (candidate.content.parts if candidate and candidate.content else None) or []
                if parts:
                    break
                print(f"[Bot] empty model response (attempt {_attempt + 1}/3) — retrying")
            fn_calls   = [p for p in parts if p.function_call]
            text_parts = [p.text for p in parts if p.text]
            if not fn_calls:
                return "\n".join(t for t in text_parts if t).strip()
            response_parts = []
            for part in fn_calls:
                fc   = part.function_call
                fn   = fn_map.get(fc.name)
                args = dict(fc.args) if fc.args else {}
                print(f"[Bot] → {fc.name}({args})")
                try:
                    result = fn(**args) if fn else f"Unknown tool: {fc.name}"
                except Exception as e:
                    result = f"Tool error: {e}"
                print(f"[Bot] ← {str(result)[:150]}")
                tools_called.append(fc.name)
                if fc.name in _action_set:
                    ok = isinstance(result, str) and not result.startswith(
                        ("Error", "⚠️", "Owner account", "No pending",
                         "Unknown tool", "Tool error", "Couldn't"))
                    action_results[fc.name] = action_results.get(fc.name, False) or ok
                    if ok:
                        # The action mutated its domain → the shown list for that domain is now
                        # stale; drop it so a later "#N" re-resolves against the live store.
                        _invalidate_shown_lists(state, fc.name)
                response_parts.append(
                    types.Part(function_response=types.FunctionResponse(
                        name=fc.name, response={"result": result})))
            contents.append(types.Content(role="model", parts=parts))
            contents.append(types.Content(role="user",  parts=response_parts))
        return ""

    def _verify_completion(candidate_reply: str) -> dict:
        """Completion gate (function 1): given the user's request + the GROUND-TRUTH of what the
        agent actually did this turn (tools_called / succeeded actions), decide whether the request
        was really fulfilled. Trust ONLY action_results, never the draft reply's own claims.
        Returns {verdict, missing, user_message}; fail-safe to 'done' so a checker error never
        blocks the turn."""
        succeeded = [n for n, ok in action_results.items() if ok]
        check_prompt = (
            "You are a completion checker for an executive assistant bot. Decide whether the bot "
            "ACTUALLY did what the user asked THIS turn. Trust the ground-truth facts below, NOT what "
            "the draft reply claims.\n\n"
            f"User's request: {effective_text}\n\n"
            f"Tools the bot called this turn: {tools_called or 'none'}\n"
            f"ACTION tools that SUCCEEDED: {succeeded or 'none'}\n"
            f"Draft reply the bot wants to send: {(candidate_reply or '')[:600]}\n\n"
            "STEP 1 — classify the request:\n"
            "  READ  = the user only wants to SEE / SHOW / LIST / FIND / CHECK / SUMMARIZE information "
            "(emails, meetings, contacts, commitments, history, 'who/what/when/did I…'). No state change.\n"
            "  ACTION = the user wants the bot to CHANGE or SEND something: schedule/create an event, "
            "draft/send an email, update/tag a contact, snooze/dismiss/mark a commitment, run outreach, "
            "draft a group email, OR run/refresh a section (run_skill).\n\n"
            "STEP 2 — pick exactly one verdict:\n"
            "- \"done\":\n"
            "    • the request is chat/greeting; OR\n"
            "    • the request is READ and the bot gave a relevant answer. CRITICAL: read/query tools "
            "(get_recent_emails, get_upcoming_meetings, find_contacts_by_name, read_module_result, "
            "check_email_handling, get_contact_history, get_email_frequency_report, list_my_groups, "
            "get_meeting_summary, …) NEVER appear in SUCCEEDED — their absence is NOT incompleteness. "
            "A READ request is done once answered; NEVER re-drive a read; OR\n"
            "    • the request is ACTION and the action IS in SUCCEEDED, OR the bot called run_skill to "
            "run/refresh the requested section (that runs in the background = done).\n"
            "- \"incomplete_actionable\": the request is ACTION, it is NOT in SUCCEEDED and the bot did NOT "
            "trigger it, yet everything needed is already known (recipient/contact/time resolved) — the bot "
            "dropped the ball and should just call the action tool. ALSO use this when the reply asks the "
            "user to pick among candidates (which person/contact/email/meeting) but NO lookup tool "
            "(e.g. find_contacts_by_name) is in 'Tools the bot called this turn' — the bot asked BLIND; it "
            "must look first, then present the matches as a [#N] list.\n"
            "- \"incomplete_needs_user\": the request is ACTION and is genuinely blocked on info only the "
            "user can give (a missing time/subject, a confirmation) — OR the bot ALREADY looked up candidates "
            "this turn (a lookup tool IS in the called list) and several genuinely match, so it correctly "
            "lists them as [#N] and asks which. A blind 'please specify' with no lookup is incomplete_actionable, NOT this.\n\n"
            "A reply that CLAIMS an action is done while that action is NOT in SUCCEEDED (and was not a "
            "run_skill trigger) is a FALSE claim → never 'done'.\n\n"
            "Return ONLY JSON: {\"verdict\":\"done|incomplete_actionable|incomplete_needs_user\","
            "\"missing\":\"<the action to call, or what to ask the user>\","
            "\"user_message\":\"<if not done: ONE honest sentence telling the user it is NOT done yet and "
            "what is needed; empty string if done>\"}"
        )
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=check_prompt,
                config=types.GenerateContentConfig())
            _record_bot_usage(resp, "bot")
            raw = (resp.text or "").strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s != -1 and e > s:
                obj = json.loads(raw[s:e + 1])
                if obj.get("verdict") in ("done", "incomplete_actionable", "incomplete_needs_user"):
                    return obj
        except Exception as ce:
            print(f"[Bot] completion check failed: {ce}")
        return {"verdict": "done"}   # fail-safe: never block the turn

    # ── Run the agent, then the completion gate ────────────
    # The user receives NOTHING until the gate converges: either the action truly succeeded,
    # or we honestly tell them it is not done and what is needed. No hollow "Done", no dropped tail.
    final_text = _run_agent_rounds(MAX_ROUNDS)

    # ── Fabricated-search guard (deterministic) ─────────────────────────────
    # A search-shaped request ("find / search / 有没有…") answered with ZERO tool calls is an
    # answer from memory/history, not a lookup — the "didn't find the file" fabrication while
    # the file existed on OneDrive. Re-drive once demanding a real search; if the model still
    # won't call a tool, fall back honestly rather than send a made-up verdict.
    _SEARCH_ASKS = ("find ", "search", "look for", "look up", "do i have", "is there",
                    "有没有", "找一下", "找找", "搜一", "搜索", "查一下", "帮我找", "帮我查")
    _asked_search = any(w in (effective_text or "").lower() for w in _SEARCH_ASKS)
    if _asked_search and final_text and not tools_called and total_rounds < MAX_ROUNDS:
        print("[Bot] fabricated-search guard — search-shaped ask answered with NO tool; re-driving")
        contents.append(types.Content(role="user", parts=[types.Part(text=(
            "[system] The user asked you to FIND/SEARCH something, but you called NO tool — your "
            "answer came from memory/history and may be wrong. Call the `search` tool NOW (pick the "
            "right `what`: emails/attachments/contacts/meetings/files — or another read tool that "
            "fits) and answer ONLY from its result."))]))
        finish_mode = "redrive"
        new_text = _run_agent_rounds(max(1, MAX_ROUNDS - total_rounds))
        if new_text and tools_called:
            final_text = new_text
        elif not tools_called:
            final_text = ""   # → empty-path below sends HONEST_FALLBACK and skips history save

    verdict     = "done"
    corrections = 0

    # ── Completion-gate relevance pre-filter (deterministic) ───────────────────
    # The gate exists to catch exactly three things: (1) an ACTION tool was attempted
    # — did it really succeed? (2) the reply CLAIMS an action it did not perform (a
    # hollow "Done!"); (3) the bot asked the user to pick among candidates WITHOUT
    # looking them up (a blind disambiguation). Pure reads / chat / honest questions
    # have NOTHING to verify — running the flaky 2.5-flash checker on them only
    # manufactured false "I couldn't retrieve…" failures and burned re-drive rounds.
    # So only enter the gate when it is actually relevant.
    _ft = (final_text or "").lower()
    _CLAIM = ("scheduled", "booked", "event created", "created the event", "draft saved",
              "saved to your", "invite sent", "invites sent", "invitation has been sent",
              "has been sent", "email sent", "i've sent", "i have sent", "i've scheduled",
              "i've created", "i've drafted", "i've saved", "i've updated", "i've tagged",
              "i've added", "i've marked", "has been scheduled", "has been created",
              "has been saved", "has been updated", "has been tagged", "has been marked",
              "marked as", "snoozed", "dismissed", "✅")
    _PICK = ("which daniel", "which one", "which of these", "which of them",
             "please specify which", "specify which", "which contact", "which person",
             "which meeting", "which email")
    _action_attempted = any(t in _action_set for t in tools_called)   # was ACTION_TOOLS (empty) → dead
    _lookup_called = any(t in ("find_contacts_by_name", "check_email_handling", "get_recent_emails",
                               "get_contact_history", "list_group_members") for t in tools_called)
    _claims_action = any(w in _ft for w in _CLAIM)
    _blind_pick    = any(p in _ft for p in _PICK) and not _lookup_called
    # Honest "I can't match #N — here's what I have" decline (the [#N] block tells the bot to
    # say this instead of punting to a refresh). It IS the complete answer — never re-drive it
    # into "do it NOW". Guarded by "no action succeeded" so stray wording can't hide a real
    # success or a falsely-claimed one.
    _any_action_ok = any(action_results.values())
    _honest_decline = (not _any_action_ok) and (
        "here's what i have" in _ft or "here is what i have" in _ft
        or ("match" in _ft and any(w in _ft for w in
            ("can't", "cannot", "can not", "couldn't", "couldn", "unable")))
    )
    if _honest_decline:
        finish_mode = "needs_user"
    _gate_relevant = (bool(_ft.strip()) and not _honest_decline
                      and (_action_attempted or _claims_action or _blind_pick))

    while _gate_relevant:
        v = _verify_completion(final_text)
        verdict = v.get("verdict", "done")
        if verdict == "done":
            break
        if verdict == "incomplete_needs_user":
            finish_mode = "needs_user"
            # needs_user means the agent is honestly ASKING the user — its own reply carries the
            # rich question (e.g. the [#N] candidate list). Prefer it; the verifier's one-liner is a
            # lossy summary ("specify which Daniel from the list" drops the list) — fallback only.
            final_text = (final_text or v.get("user_message") or HONEST_FALLBACK).strip()
            break
        # incomplete_actionable — re-drive the same agent if budget allows
        if corrections >= MAX_CORRECTIONS or total_rounds >= MAX_ROUNDS:
            finish_mode = "exhausted"
            final_text = ((v.get("user_message") or "").strip()
                          or (f"I haven't completed that yet — {v.get('missing','')}").strip()
                          or HONEST_FALLBACK)
            break
        corrections += 1
        finish_mode = "redrive"
        contents.append(types.Content(role="user", parts=[types.Part(text=(
            f"[system] You did NOT actually complete this. Next step: "
            f"{v.get('missing','call the action tool the user asked for')}. "
            "Do it NOW with the tools. If you need to resolve a named person/target first, call the lookup "
            "tool (find_contacts_by_name) BEFORE anything else, then either complete the action or — only if "
            "several candidates genuinely match — list them as a [#N] list and ask which one. Do not just "
            "describe it, claim it is done, or ask the user to specify without first looking them up."
        ))]))
        new_text = _run_agent_rounds(max(1, MAX_ROUNDS - total_rounds))
        if new_text:
            final_text = new_text

    # If the model never produced any text at all, fall back honestly (don't send empty).
    if not final_text:
        finish_mode = "fallback"
        final_text = HONEST_FALLBACK

    # List-completeness guard (approaches 1+3): if the model truncated a list section it read
    # this turn, substitute the deterministic full render so nothing is silently dropped.
    final_text = _enforce_list_completeness(final_text, state, text)

    # Append Outlook draft link if create_reply_draft saved one this turn
    web_link = state.pop("_last_draft_web_link", None)
    if web_link:
        from src.modules.links import wrap_draft_link
        final_text += f"\n\n<a href='{wrap_draft_link(web_link)}'>📬 Open draft in Outlook</a>"

    event_link = state.pop("_last_event_web_link", None)
    if event_link:
        from src.modules.links import wrap_draft_link
        final_text += f"\n\n<a href='{wrap_draft_link(event_link)}'>📅 Open event in Outlook</a>"

    actions_ok   = [n for n, ok in action_results.items() if ok]
    actions_fail = [n for n, ok in action_results.items() if not ok]
    print(f"[Bot] turn done — rounds={total_rounds}/{MAX_ROUNDS} finish={finish_mode} "
          f"verdict={verdict} corrections={corrections} "
          f"tools={tools_called} actions_ok={actions_ok} actions_failed={actions_fail}")

    # Don't persist a FAILED turn (model returned nothing → honest fallback). Saving it would write a
    # "this question → empty/fallback" pair into the replayed history, and an autoregressive model
    # tends to MIMIC that pattern — so an identical repeat question keeps returning empty (the turn
    # poisons itself). Dropping failed turns keeps history clean; the user's retry/rephrase starts fresh.
    # Also drop a POISONED turn: a reply that listed a stored record (contacts / [#N] list / an email)
    # with NO tool call this turn — it was answered from memory/replayed history, not a fresh lookup.
    # Persisting it flat teaches the model to parrot the stale answer next time instead of calling the
    # tool (the "draft to jason → backed a stale ips/proxy list, tools=[]" bug). See _is_poisoned_turn.
    _poisoned = _is_poisoned_turn(final_text, tools_called)
    if finish_mode != "fallback" and not _poisoned:
        _save_turn(db_path, text, final_text)
    elif _poisoned:
        print("[Bot] turn NOT saved — answered from memory (record listing with no tool call) "
              f"finish={finish_mode}")
    else:
        # Dropped from history — carry the ask in state so the user's "try again" has a referent.
        _record_failed_ask(state, text, _prev_failed)
        print("[Bot] fallback turn — NOT saved to history (avoids empty-response feedback loop)")
    return final_text, state
