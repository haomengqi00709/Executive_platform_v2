"""
Bot — Gemini function calling orchestrator.

Entry point: reply(state, text, graph, owner_graph, settings, wiki_dir, data_dir, user_model_path)
Returns: (reply_text, updated_state)
"""
import json
import os
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
from src.modules.wiki import load_index, load_meeting

MODEL        = DEFAULT_GEMINI_MODEL
MAX_ROUNDS   = 8
HISTORY_LIMIT = 20


def _with_indices(items: list[dict]) -> list[dict]:
    """Prefix each item with a 1-based `index` field. Single source of truth
    for the [#N] convention all list-returning tools share — the AI displays
    items as `[#N] …` and resolves user's later `#N` references against the
    canonical IDs (email_id / event_id / draft_id / …) on each item."""
    return [{"index": i + 1, **(it or {})} for i, it in enumerate(items or [])]

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


def _client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


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
        d = json.loads((data_dir / "email_monitor.json").read_text())
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

    # ── System prompt ──────────────────────────────────────
    display_name     = settings.get("display_name", "the executive")
    business_context  = load_profile_context(data_dir)
    writing_style     = settings.get("writing_style_note", "").strip()
    timezone_str      = settings.get("timezone", "UTC")
    now_str           = datetime.now(timezone.utc).strftime("%A, %B %d, %Y %H:%M UTC")
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

    pending_note = ""
    pending_draft   = state.get("pending_draft")
    pending_expense = state.get("pending_expense")
    pending_queue   = state.get("pending_queue") or []

    if pending_draft:
        subj  = pending_draft.get("subject", "")
        to    = pending_draft.get("to", "")
        extra = f" ({len(pending_queue)} more in queue)" if pending_queue else ""
        pending_note += (
            f"\n\n⚠️ PENDING EMAIL DRAFT — Subject: '{subj}', To: {to}{extra}. "
            f"If the user is clearly responding to THIS draft (approve/yes/send/ok) → call approve_draft(). "
            f"If they clearly want to skip THIS draft (skip/no/not now, with no item numbers) → call skip_draft(). "
            f"If the user mentions item numbers or commitments, they are NOT responding to the draft — handle accordingly."
        )

    if pending_expense:
        vendor = pending_expense.get("new_row", {}).get("Vendor", "?")
        amount = pending_expense.get("new_row", {}).get("Amount", "?")
        pending_note += (
            f"\n\n⚠️ PENDING EXPENSE DUPLICATE — {vendor} {amount}. "
            f"If the user says YES → call confirm_expense(). "
            f"If they say NO → call discard_expense()."
        )

    system = (
        f"You are an AI executive assistant for {display_name}.{bc_line}{style_line}\n\n"
        f"Today: {now_str}. Timezone: {timezone_str}.\n"
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
        f"  look up item N in the MOST RECENT list-returning tool output above in this\n"
        f"  conversation. Read its canonical ID from the JSON and pass that ID (or the\n"
        f"  to/subject/etc fields off that item) into the action tool. NEVER retype\n"
        f"  subjects, recipients, or names from memory — copy them from the JSON output.\n\n"
        f"  If the user says #N but no recent list is visible in this conversation,\n"
        f"  ask which list they mean (or re-run the appropriate read tool first).\n\n"
        f"TOOL ROUTING:\n"
        f"  get_recent_emails          → 'show my emails', 'what did X send', 'unread messages'\n"
        f"  get_upcoming_meetings      → 'what meetings do I have', 'who is in my next call'\n"
        f"  get_contact_history        → 'history with X', 'last email from John'\n"
        f"  get_email_frequency_report → 'who do I email most', 'most active contacts'\n"
        f"  read_module_result         → 'what did the briefing say', 'show last email analysis'\n"
        f"  check_email_handling       → 'did I reply to Sarah?', 'what happened with the Acme email?', 'has the X thread been handled?'\n"
        f"                               Reports whether the email is still open or already handled (replied / drafted / subject_match / meeting).\n"
        f"  get_meeting_summary        → 'what did we decide in the Q3 meeting?', 'summarize my meeting with John', 'recap last week's sync'\n"
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
        f"  dismiss_commitment         → 'skip 2', 'skip 3 4', 'skip 2 3 4' — skip means permanent dismiss\n"
        f"  snooze_commitment          → 'snooze 2', 'remind me in 3 days about 3', 'snooze 2 3 4 for 5 days'\n"
        f"  create_reply_draft         → 'draft a reply to X', 'write an email to Y', 'compose a response'\n"
        f"                               First call get_recent_emails to find the email, compose the full body, then save.\n"
        f"                               Draft is saved immediately to Outlook — no approval step needed.\n"
        f"  approve_draft / skip_draft → only when a pending draft is shown above\n"
        f"  confirm_expense / discard_expense → only when a pending expense is shown above\n"
        f"  update_crm_contact         → 'mark X as high priority', 'add note to Sarah', 'set company for John'\n"
        f"  create_calendar_event      → 'schedule meeting with X', 'block my calendar Friday', 'create Teams call'\n"
        f"  run_outreach               → 'draft outreach for the people I met at X', 'batch email contacts from OneDrive folder', 'draft outreach for everyone tagged Y'\n"
        f"                               Three modes (pick one): folder= (OneDrive), tag= (CRM by tag), recent_hours= (CRM by recency)\n"
        f"  tag_recent_contacts        → 'tag everyone I just added as X', 'group these contacts as Calgary Summit 2026'\n\n"
        f"AVAILABLE SECTIONS (use these exact section_id values for run_skill, "
        f"read_skill_instruction, update_skill_instruction):\n"
        + "".join(
            f"  {sid:30s} → {desc.split(' — ', 1)[1] if ' — ' in desc else desc}\n"
            for sid, desc in SECTION_IDS.items()
        )
        + (
            f"\nHONESTY RULE: When a tool returns an error or an unexpected result, "
            f"REPORT IT honestly to the user. Do NOT reply 'Done' or pretend success "
            f"when the tool failed. Show what went wrong and what you did/didn't do."
        )
        + f"{user_ctx}"
        + f"{session_ctx}"
        + f"{pending_note}"
    )

    # ── Tool definitions ───────────────────────────────────

    # --- Query tools ---

    def get_recent_emails(hours_back: int = 48, top: int = 15) -> str:
        """Get emails received in the last N hours. Each item carries `index` (1-based)
        and `email_id` (canonical Graph id) so the user can later refer to emails by
        #N and you can call action tools with the resolved email_id."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            msgs   = owner_graph.get_messages(top=top)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            result = []
            for m in msgs:
                recv = m.get("receivedDateTime", "")
                try:
                    dt = datetime.fromisoformat(recv.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
                result.append({
                    "email_id":   m.get("id", ""),
                    "subject":    m.get("subject", ""),
                    "from":       m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received":   recv[:16],
                    "preview":    (m.get("bodyPreview") or "")[:200],
                    "is_read":    m.get("isRead", True),
                    "importance": m.get("importance", "normal"),
                })
            result = _with_indices(result)
            print(f"[Bot] get_recent_emails({hours_back}h) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def get_upcoming_meetings(hours_ahead: int = 24) -> str:
        """Get calendar meetings in the next N hours. Each item carries `index` and
        `event_id` (canonical Graph calendar event id) so the user can refer to a
        meeting by #N and you can call get_meeting_summary with the event_id."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            now    = datetime.now(timezone.utc)
            end_dt = now + timedelta(hours=hours_ahead)
            events = owner_graph.get_calendar_view(
                start_dt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_dt=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                top=20,
            )
            result = []
            for e in events:
                attendees = [
                    a.get("emailAddress", {}).get("address", "")
                    for a in (e.get("attendees") or [])
                ]
                result.append({
                    "event_id":  e.get("id", ""),
                    "title":     e.get("subject", ""),
                    "start":     (e.get("start") or {}).get("dateTime", "")[:16],
                    "end":       (e.get("end") or {}).get("dateTime", "")[:16],
                    "attendees": attendees,
                    "location":  e.get("location", {}).get("displayName", ""),
                })
            result = _with_indices(result)
            print(f"[Bot] get_upcoming_meetings({hours_ahead}h) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def get_contact_history(email: str) -> str:
        """Get email and meeting history with a specific contact by their email address."""
        try:
            result = {"email": email, "emails": [], "meetings": []}
            if wiki_dir and wiki_dir.exists():
                index_path = wiki_dir / "_index.json"
                if index_path.exists():
                    index = json.loads(index_path.read_text())
                    for proj_id, proj in index.items():
                        participants = proj.get("participants") or []
                        if any(
                            email.lower() in (p.lower() if isinstance(p, str) else "")
                            for p in participants
                        ):
                            proj_path = wiki_dir / f"{proj_id}.json"
                            if proj_path.exists():
                                proj_data = json.loads(proj_path.read_text())
                                result["meetings"].extend(proj_data.get("meetings", [])[:5])
                                result["emails"].extend(proj_data.get("emails", [])[:5])
            # Attach CRM writing style if available — used by Gemini when drafting emails to this contact
            if data_dir:
                try:
                    from src.modules.crm import load_crm
                    crm = load_crm(data_dir)
                    contact = crm.get("contacts", {}).get(email.lower(), {})
                    ws = contact.get("writing_style", "").strip()
                    if ws:
                        result["writing_style_note"] = ws
                except Exception:
                    pass
            # Independent 1-based index on each sub-list so the user can say
            # "tell me about meeting #2" or "draft for email #3".
            result["emails"]   = _with_indices(result["emails"])
            result["meetings"] = _with_indices(result["meetings"])
            print(f"[Bot] get_contact_history({email})")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def get_email_frequency_report(days_back: int = 30, top_n: int = 10) -> str:
        """Analyze email frequency by sender over the past N days. Shows who you communicate with most."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            msgs   = owner_graph.get_messages(top=200)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
            counts: Counter = Counter()
            for m in msgs:
                recv = m.get("receivedDateTime", "")
                try:
                    dt = datetime.fromisoformat(recv.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
                sender = m.get("from", {}).get("emailAddress", {}).get("address", "")
                if sender:
                    counts[sender] += 1
            result = _with_indices([
                {"email": email, "email_count": count}
                for email, count in counts.most_common(top_n)
            ])
            print(f"[Bot] get_email_frequency_report({days_back}d) → {len(result)} contacts")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def read_module_result(section_id: str) -> str:
        """Read the latest cached result for a section. If the result contains an
        `items` list, each item gets a 1-based `index` field added so the user can
        refer to items by #N. Canonical IDs (email_id / id / project_id …) stay on
        each item so you can call action tools with them.

        section_id must be one of: ai_summary, market_intelligence, company_intelligence,
        reply_needed, followup_needed, commitments_extract, upcoming_commitments,
        recent_meetings, meeting_action_items, relationship_health, business_insights, expenses"""
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        result_path = data_dir / "results" / f"{section_id}.json"
        if not result_path.exists():
            return f"No results for '{section_id}' yet. Run the section first with run_skill()."
        try:
            data = json.loads(result_path.read_text())
            # Decorate items[] in place with index. Sidecar lists like handled[]
            # also get indexed so `check_email_handling` and follow-up references
            # stay consistent.
            if isinstance(data.get("items"), list):
                data["items"] = _with_indices(data["items"])
            if isinstance(data.get("handled"), list):
                data["handled"] = _with_indices(data["handled"])
            print(f"[Bot] read_module_result({section_id})")
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading {section_id}: {e}"

    def search_web(query: str) -> str:
        """Search the web for current news, market data, or any information not in the user's inbox/calendar."""
        try:
            client = _client()
            resp   = client.models.generate_content(
                model=MODEL,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            result = resp.text or "No results found."
            print(f"[Bot] search_web → {len(result)} chars")
            return result
        except Exception as e:
            return f"Search error: {e}"

    # --- Config tools ---

    def read_settings(key: str = None) -> str:
        """Read current settings and user preferences. Optionally pass a key to get one value.
        Top-level keys include: display_name, timezone, check_interval_hours.
        Business profile and market segments live in profile/business_profile.md and profile/market_segments.md.
        User model keys include: ignored_senders, behavioral_rules, key_relationships."""
        combined = {**settings, "user_model": user_model}
        if key:
            if key in settings:
                return json.dumps({key: settings[key]}, ensure_ascii=False)
            if key in user_model:
                return json.dumps({key: user_model[key]}, ensure_ascii=False)
            return f"Key '{key}' not found in settings or user model."
        print(f"[Bot] read_settings()")
        return json.dumps(combined, ensure_ascii=False)

    def update_setting(key: str, value: str) -> str:
        """Update a user preference. Writes to user_model.json.
        Supported keys: ignored_senders (JSON list of emails), behavioral_rules (JSON list of strings),
        key_relationships (JSON dict of email→note), check_interval_hours (number as string),
        briefing_style (string),
        email_digest_interval_hours (number as string, 0=disable digest, default 2),
        email_realtime_push (true/false — whether priority emails push immediately).
        Pass lists/dicts as JSON strings, e.g. '["a@b.com"]'."""
        nonlocal user_model
        import json as _j
        try:
            parsed = _j.loads(value)
        except Exception:
            parsed = value
        user_model = {**user_model, key: parsed}
        _save_user_model(user_model_path, user_model)
        print(f"[Bot] update_setting({key}={parsed!r})")
        return f"✅ Preference updated: {key}"

    def read_skill_instruction(section_id: str) -> str:
        """Read the current custom instructions for a section. Always call this BEFORE updating,
        so you can append new rules rather than overwrite existing ones.

        section_id must be one of:
          ai_summary           — Morning Briefing (daily summary of calendar, emails, priorities)
          market_intelligence  — Market Intelligence (industry news, competitor updates)
          company_intelligence — Company Intelligence (targeted signals on monitored companies)
          reply_needed         — Emails Awaiting Reply (inbox emails waiting for your response)
          followup_needed      — Sent — No Response (emails you sent, other party hasn't replied)
          commitments_extract  — Commitments Extracted (promises and deadlines from emails)
          upcoming_commitments — Upcoming Commitments (deadlines and commitments in next 2 weeks)
          recent_meetings      — Recent Meetings (summaries from recorded meetings)
          meeting_action_items — Meeting Action Items (open action items from meetings)
          relationship_health  — Relationship Health (health scores for key business contacts)
          business_insights    — Business Insights (AI analysis of business patterns)
          expenses             — Expense Capture (receipts and invoices)
          email_monitor        — Email Monitor Triage (rules for priority/review/skip classification)
        """
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        path = data_dir / "instructions" / f"{section_id}.md"
        content = path.read_text().strip() if path.exists() else ""
        print(f"[Bot] read_skill_instruction({section_id})")
        return content if content else "(no custom instructions yet)"

    def update_skill_instruction(section_id: str, content: str) -> str:
        """Update the custom instructions for a section. These instructions override the default
        AI behavior for that section on the next run. IMPORTANT: always call read_skill_instruction
        first, then append your new rules to the existing content — do not discard prior rules.

        section_id must be one of the keys in SECTION_IDS — see the TOOL ROUTING list
        above for the catalog of available sections.
        """
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"
        path = data_dir / "instructions" / f"{section_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"[Bot] update_skill_instruction({section_id}) → {len(content)} chars")
        return f"✅ Instructions updated for: {SECTION_IDS[section_id].split(' — ')[0]}"

    # --- Trigger tool ---

    def run_skill(section_id: str) -> str:
        """Trigger a section to run immediately in the background. When done, the
        formatted result is auto-pushed to Teams chat AND written to the dashboard.

        section_id must be one of the keys in SECTION_IDS — see the TOOL ROUTING
        list above for the catalog of available sections."""
        if section_id not in SECTION_IDS:
            return f"Unknown section '{section_id}'. Available: {', '.join(SECTION_IDS)}"

        owner_uid = state.get("owner_uid", "")
        if not owner_uid:
            return "Cannot run section — owner user ID not found in bot state."

        def _run():
            try:
                from src.server import _run_section_for_user
                _run_section_for_user(owner_uid, section_id)
            except Exception as e:
                print(f"[Bot] run_skill {section_id} error: {e}")

        import threading
        threading.Thread(target=_run, daemon=True).start()
        label = SECTION_IDS[section_id].split(" — ")[0]
        print(f"[Bot] run_skill({section_id}) → started")
        return f"✅ {label} is running. Results will appear in your dashboard shortly."

    # --- Action tools ---

    def _resolve_commitment(index_or_hint: str) -> tuple[str | None, str]:
        """Return (commitment_id, description) by 1-based index or keyword match."""
        try:
            path = data_dir / "results" / "commitments_extract.json"
            if not path.exists():
                return None, ""
            data = json.loads(path.read_text())
            items = data.get("items", [])
            try:
                idx = int(index_or_hint) - 1
                if 0 <= idx < len(items):
                    return items[idx]["id"], items[idx].get("description", "")
            except ValueError:
                hint = index_or_hint.lower()
                for item in items:
                    if hint in (item.get("description") or "").lower():
                        return item["id"], item.get("description", "")
        except Exception:
            pass
        return None, ""

    def mark_commitment_done(index_or_hint: str) -> str:
        """Mark a commitment as completed so it no longer appears in the commitments list.
        index_or_hint: the number shown in the commitments list (e.g. "2"), or a keyword from the description.
        Use "all" to mark everything currently flagged as stale as done."""
        from src.modules.commitments_state import mark_done as _mark_done, load_state as _load_state
        if index_or_hint.strip().lower() == "all":
            state = _load_state(data_dir)
            asked_ids = list(state.get("asked", {}).keys())
            for cid in asked_ids:
                _mark_done(data_dir, cid, method="user")
            print(f"[Bot] mark_commitment_done(all) → {len(asked_ids)} items")
            return f"✅ Marked {len(asked_ids)} commitments as done."
        cid, desc = _resolve_commitment(index_or_hint)
        if not cid:
            return f"⚠️ Couldn't find commitment '{index_or_hint}'. Run commitments_extract first."
        _mark_done(data_dir, cid, method="user")
        print(f"[Bot] mark_commitment_done({index_or_hint!r}) → {cid}")
        return f"✅ Done: \"{desc}\""

    def snooze_commitment(index_or_hint: str, days: int = 3) -> str:
        """Snooze one or more commitments — hide them for N days, then resurface automatically.
        index_or_hint: single number, space/comma-separated numbers ("2 3 4"), or keyword.
        days: how many days to snooze (default 3)."""
        from src.modules.commitments_state import mark_snoozed as _mark_snoozed
        from datetime import date, timedelta
        # Support multiple indices: "2 3 4" or "2,3,4"
        tokens = [t.strip() for t in index_or_hint.replace(",", " ").split() if t.strip()]
        if len(tokens) > 1 and all(t.isdigit() for t in tokens):
            snoozed = []
            for t in tokens:
                cid, desc = _resolve_commitment(t)
                if cid:
                    _mark_snoozed(data_dir, cid, days=days)
                    snoozed.append(desc)
            if not snoozed:
                return f"⚠️ Couldn't find commitments '{index_or_hint}'."
            until = (date.today() + timedelta(days=days)).strftime("%B %d")
            print(f"[Bot] snooze_commitment({tokens}, {days}d)")
            return f"⏰ Snoozed {len(snoozed)} commitments until {until}."
        cid, desc = _resolve_commitment(index_or_hint)
        if not cid:
            return f"⚠️ Couldn't find commitment '{index_or_hint}'."
        _mark_snoozed(data_dir, cid, days=days)
        print(f"[Bot] snooze_commitment({index_or_hint!r}, {days}d) → {cid}")
        until = (date.today() + timedelta(days=days)).strftime("%B %d")
        return f"⏰ Snoozed until {until}: \"{desc}\""

    def dismiss_commitment(index_or_hint: str) -> str:
        """Permanently remove one or more commitments — they will never appear again.
        Use for 'skip X', 'skip 2 3 4', or when a commitment is cancelled/irrelevant.
        index_or_hint: number, space/comma-separated numbers ("2 3 4"), keyword, or "all"."""
        from src.modules.commitments_state import mark_done as _mark_done, load_state as _load_state
        if index_or_hint.strip().lower() == "all":
            state = _load_state(data_dir)
            asked_ids = list(state.get("asked", {}).keys())
            for cid in asked_ids:
                _mark_done(data_dir, cid, method="user_dismissed")
            return f"✅ Dismissed {len(asked_ids)} commitments."
        # Support multiple indices: "2 3 4" or "2,3,4"
        tokens = [t.strip() for t in index_or_hint.replace(",", " ").split() if t.strip()]
        if len(tokens) > 1 and all(t.isdigit() for t in tokens):
            dismissed = []
            for t in tokens:
                cid, desc = _resolve_commitment(t)
                if cid:
                    _mark_done(data_dir, cid, method="user_dismissed")
                    dismissed.append(desc)
            if not dismissed:
                return f"⚠️ Couldn't find commitments '{index_or_hint}'."
            print(f"[Bot] dismiss_commitment({tokens})")
            return f"🗑️ Skipped {len(dismissed)} commitments."
        cid, desc = _resolve_commitment(index_or_hint)
        if not cid:
            return f"⚠️ Couldn't find commitment '{index_or_hint}'."
        _mark_done(data_dir, cid, method="user_dismissed")
        print(f"[Bot] dismiss_commitment({index_or_hint!r}) → {cid}")
        return f"🗑️ Skipped: \"{desc}\""

    def create_reply_draft(to: str, subject: str, body: str) -> str:
        """Compose and immediately save a new email draft to Outlook Drafts.
        Call this when the user asks to draft, write, or compose an email reply.
        to: recipient email address
        subject: email subject line (prefix 'Re: ' for replies)
        body: email body in the user's writing style — do NOT write a sign-off.
              A signature (user's real one, extracted from sent history) is
              appended automatically; writing your own creates a double sign-off.
        IMPORTANT: after this tool succeeds, respond with ONE short sentence only —
        e.g. 'Done, draft saved to your Outlook Drafts.' Do NOT repeat To/Subject/Body.
        Do NOT generate any links or URLs yourself — a link is appended automatically."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            final_body = append_signature_to_body(body, get_user_signature(settings))
            result = owner_graph.create_draft(to=to, subject=subject, body=final_body)
            web_link = result.get("webLink", "")
            print(f"[Bot] create_reply_draft saved → '{subject}'")
            if web_link:
                state["_last_draft_web_link"] = web_link
            return f"✅ Draft saved to Outlook Drafts: '{subject}' to {to}."
        except Exception as e:
            return f"Error saving draft: {e}"

    def list_pending_drafts() -> str:
        """List all pending email drafts waiting for approval. Returns JSON with
        `index` per item — index 1 is the CURRENT draft (the one approve_draft /
        skip_draft will act on), indices 2+ are the queued drafts behind it.
        Each item carries `to`, `subject`, `body` (truncated)."""
        nonlocal state
        queue   = list(state.get("pending_queue") or [])
        current = state.get("pending_draft")
        if not current and not queue:
            return json.dumps({"pending": [], "note": "No pending drafts."}, ensure_ascii=False)

        def _shape(d: dict, is_current: bool) -> dict:
            return {
                "to":         d.get("to", ""),
                "subject":    d.get("subject", ""),
                "body":       (d.get("body") or "")[:400],
                "is_current": is_current,
            }

        items: list[dict] = []
        if current:
            items.append(_shape(current, True))
        for d in queue:
            items.append(_shape(d, False))
        return json.dumps({"pending": _with_indices(items)}, ensure_ascii=False)

    def approve_draft() -> str:
        """Approve and save the current pending email draft to the user's Outlook Drafts folder."""
        nonlocal state
        draft = state.get("pending_draft")
        if not draft:
            return "No pending draft to approve."
        if owner_graph is None:
            return "Owner account not available."
        try:
            final_body = append_signature_to_body(draft.get("body", ""), get_user_signature(settings))
            result = owner_graph.create_draft(
                to      = draft.get("to", ""),
                subject = draft.get("subject", ""),
                body    = final_body,
            )
            queue      = list(state.get("pending_queue") or [])
            next_draft = queue[0] if queue else None
            state = {**state, "pending_draft": next_draft, "pending_queue": queue[1:] if queue else []}
            print(f"[Bot] approve_draft → '{draft.get('subject')}'")
            web_link = result.get("webLink", "")
            nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
            if web_link:
                from src.modules.links import wrap_draft_link
                return f"✅ Draft saved — <a href='{wrap_draft_link(web_link)}'>Open in Outlook to review and send</a>{nxt}"
            return f"✅ Draft saved to Outlook Drafts: '{draft.get('subject')}'{nxt}"
        except Exception as e:
            return f"Error saving draft: {e}"

    def skip_draft() -> str:
        """Skip/dismiss the current pending email draft without saving it."""
        nonlocal state
        draft = state.get("pending_draft")
        if not draft:
            return "No pending draft to skip."
        queue      = list(state.get("pending_queue") or [])
        next_draft = queue[0] if queue else None
        state = {**state, "pending_draft": next_draft, "pending_queue": queue[1:] if queue else []}
        print(f"[Bot] skip_draft → '{draft.get('subject')}'")
        nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
        return f"Skipped: '{draft.get('subject')}'{nxt}"

    def confirm_expense() -> str:
        """Confirm and record the pending duplicate expense as a new entry."""
        nonlocal state
        pending = state.get("pending_expense")
        if not pending:
            return "No pending expense to confirm."
        try:
            import openpyxl
            from pathlib import Path as _Path
            master_file  = _Path(pending["master_file"])
            expenses_dir = _Path(pending["expenses_dir"])
            hashes_file  = _Path(pending["hashes_file"]) if pending.get("hashes_file") else None

            expenses_dir.mkdir(parents=True, exist_ok=True)
            from src.modules.m05_expense import _append_row, _init_workbook, _load_hashes, _save_hashes
            wb = openpyxl.load_workbook(master_file) if master_file.exists() else _init_workbook()
            _append_row(wb.active, pending["new_row"])
            wb.save(master_file)
            if hashes_file and pending.get("hash") and not pending.get("is_hash_dup"):
                hashes = _load_hashes(hashes_file)
                hashes[pending["hash"]] = pending["new_row"].get("Attachment", "")
                _save_hashes(hashes, hashes_file)
            state = {**state, "pending_expense": None}
            return "✅ Expense recorded as a new entry."
        except Exception as e:
            return f"Error confirming expense: {e}"

    def discard_expense() -> str:
        """Discard the pending duplicate expense without recording it."""
        nonlocal state
        state = {**state, "pending_expense": None}
        return "Expense discarded."

    def update_crm_contact(email: str, field: str, value: str) -> str:
        """Update a field on a CRM contact. Creates the contact if it doesn't exist.
        Fields:
          priority    — high / medium / low / none
          notes       — free text, APPENDED with date stamp (not overwritten)
          company     — company name string
          name        — display name string
          ignore      — true / false (blocks email notifications from this sender)
        Use get_contact_history first to confirm the correct email address."""
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import update_contact
            contact = update_contact(data_dir, email, field, value)
            return f"✅ Updated {field} for {email}: {value}"
        except Exception as e:
            return f"Error updating CRM contact: {e}"

    def create_calendar_event(subject: str, start_iso: str, end_iso: str,
                              attendee_emails: str = "",
                              location: str = "",
                              is_online_meeting: bool = False) -> str:
        """Create a calendar event in the user's Outlook calendar.
        start_iso / end_iso: ISO 8601 format in the user's local timezone
          e.g. '2026-05-30T14:00:00' — convert natural language time using the timezone in your context.
        attendee_emails: comma-separated email addresses (leave empty for solo blocks).
        is_online_meeting: set true to add a Teams meeting link."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            attendees = [a.strip() for a in attendee_emails.split(",") if a.strip()] if attendee_emails else []
            result = owner_graph.create_event(
                subject=subject,
                start=start_iso,
                end=end_iso,
                attendees=attendees or None,
                location=location or None,
                timezone=settings.get("timezone", "UTC"),
                is_online=is_online_meeting,
            )
            event_id = result.get("id", "")
            web_link = result.get("webLink", "")
            msg = f"✅ Event created: '{subject}' from {start_iso} to {end_iso}"
            if attendees:
                msg += f" · Invites sent to: {', '.join(attendees)}"
            if web_link:
                state["_last_draft_web_link"] = web_link
            return msg
        except Exception as e:
            return f"Error creating event: {e}"

    def run_outreach(context_note: str = "", folder: str = "",
                     tag: str = "", recent_hours: int = 0) -> str:
        """Batch-generate personalized email drafts. Three modes — use ONE:

        folder       — scan a OneDrive folder for cards/csv/xlsx/pdf and draft per contact found.
                       e.g. folder='Conferences/TechConf'. Empty uses settings.outreach_folder.
        tag          — pull contacts from CRM tagged with this label (case-insensitive substring).
                       e.g. tag='Calgary Energy Summit 2026'.
        recent_hours — pull contacts from CRM added in the last N hours.
                       e.g. recent_hours=24 for "contacts I added today".

        context_note: brief context injected into each draft (e.g. 'met at TechConf').
                      Always ask the user for this if not obvious from the conversation.

        Drafts are saved to Outlook Drafts — user manually reviews and sends each one.
        Note: when users send business cards in Teams chat, drafts are AUTO-generated already;
        this tool is for batch operations on existing CRM contacts or OneDrive uploads."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            from src.modules.outreach import run as _run_outreach
            from src.ai import AIClient
            _ai = AIClient()
            result = _run_outreach(
                graph=owner_graph,
                ai=_ai,
                data_dir=data_dir,
                settings=settings,
                context_note=context_note,
                folder=folder,
                tag=tag,
                recent_hours=recent_hours,
            )
            if result.get("status") == "not_run":
                return f"❌ {result.get('error', 'Unknown error')}"
            s = result.get("summary", {})
            msg = (f"✅ Outreach run complete:\n"
                   f"  • {s.get('drafts', 0)} drafts saved to Outlook\n"
                   f"  • {s.get('skipped', 0)} contacts skipped (missing email or generation failed)")
            if s.get("files"):
                msg += f"\n  • {s['files']} files processed"
            if s.get("errors", 0):
                msg += f"\n  • {s['errors']} errors"
            return msg
        except Exception as e:
            return f"Error running outreach: {e}"

    def tag_recent_contacts(tag: str, hours: int = 24) -> str:
        """Tag all contacts added to CRM in the last N hours with a group label.
        Use when the user says 'tag everyone I just added as X' or similar.
        Existing tags are preserved (this adds to the list, not replaces).
        Returns the count of contacts tagged."""
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import tag_contacts_added_since
            n = tag_contacts_added_since(data_dir, tag, hours)
            if n == 0:
                return f"No contacts found added in the last {hours}h."
            return f"✅ Tagged {n} contact{'s' if n != 1 else ''} with '{tag}'."
        except Exception as e:
            return f"Error tagging contacts: {e}"

    def dismiss_email_followup(from_name_or_subject: str) -> str:
        """Remove a specific email from the unreplied follow-up reminder list.
        Use this when the user says they've already handled an email (by phone, in person, etc.)
        and no longer wants to be reminded about it.
        DO NOT use this to permanently block emails from a sender — use update_skill_instruction for that.
        Match by sender name or subject (partial match, case-insensitive)."""
        if not data_dir:
            return "No data directory available."
        monitor_path = data_dir / "email_monitor.json"
        if not monitor_path.exists():
            return "No email monitor state found."
        try:
            import json as _j
            monitor = _j.loads(monitor_path.read_text())
            followups = monitor.get("pending_priority_followup") or []
            query = from_name_or_subject.lower()
            before = len(followups)
            remaining = [
                f for f in followups
                if query not in f.get("from_name", "").lower()
                and query not in f.get("from", "").lower()
                and query not in f.get("subject", "").lower()
            ]
            removed = before - len(remaining)
            if removed == 0:
                return f"No follow-up reminder matched '{from_name_or_subject}'."
            monitor["pending_priority_followup"] = remaining
            monitor_path.write_text(_j.dumps(monitor, indent=2, ensure_ascii=False))
            return f"✅ Removed {removed} follow-up reminder(s) matching '{from_name_or_subject}'."
        except Exception as e:
            return f"Error: {e}"

    def check_email_handling(query: str) -> str:
        """Check whether a recent email (in reply_needed / followup_needed) has been handled,
        and if so HOW (replied / drafted / subject_match / meeting).

        query: free-text hint matching sender/recipient name, email address, or any subject keyword.
        Use when the user asks 'did I reply to X?', 'what happened with X's email?',
        'has the X thread been handled?'. Returns up to 8 matches in JSON.

        Each result contains: section, email_id, subject, who (sender or recipient),
        status='open' (still in items[]) or 'handled' (in handled[] sidecar) with handled_by detail."""
        if not data_dir:
            return "No data directory available."
        q = (query or "").strip()
        if not q:
            return "Please provide a query (sender name, subject keyword, etc.)."
        q_low = q.lower()
        q_norm = normalize_subject(q)

        def _scan(section_id: str, who_key: str) -> list[dict]:
            path = data_dir / "results" / f"{section_id}.json"
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text())
            except Exception:
                return []
            out = []
            who_name_key = "from_name" if who_key == "from_email" else "to_name"
            # Open items (still need attention)
            for it in (data.get("items") or []):
                subj = it.get("subject") or ""
                who_email = (it.get(who_key) or "")
                who_name = (it.get(who_name_key) or "")
                hay = f"{subj} {who_name} {who_email}".lower()
                hay_norm = normalize_subject(subj)
                if q_low in hay or (q_norm and q_norm in hay_norm):
                    out.append({
                        "section":  section_id,
                        "email_id": it.get("email_id"),
                        "subject":  subj,
                        "who":      who_email,
                        "status":   "open",
                    })
            # Handled sidecar (auto-detected as resolved)
            for h in (data.get("handled") or []):
                hay = f"{h.get('email_subject','')} {h.get('email_from','')} {h.get('email_to','')}".lower()
                hay_norm = normalize_subject(h.get("email_subject", ""))
                if q_low in hay or (q_norm and q_norm in hay_norm):
                    out.append({
                        "section":    section_id,
                        "email_id":   h.get("email_id"),
                        "subject":    h.get("email_subject"),
                        "who":        h.get("email_from") or h.get("email_to"),
                        "status":     "handled",
                        "handled_by": h.get("handled_by"),
                    })
            return out

        matches = _scan("reply_needed", "from_email") + _scan("followup_needed", "to_email")

        # Dedup by (section, email_id)
        seen = set()
        unique = []
        for m in matches:
            key = (m["section"], m["email_id"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)

        print(f"[Bot] check_email_handling({query!r}) → {len(unique)} matches")
        if not unique:
            return json.dumps({
                "matches": [],
                "note": f"No recent email matches '{query}' in reply_needed or followup_needed. "
                        f"The system only tracks emails from the last 14 days.",
            }, ensure_ascii=False)
        return json.dumps({"matches": _with_indices(unique[:8])}, ensure_ascii=False)

    def get_meeting_summary(event_id_or_subject: str) -> str:
        """Look up a meeting summary. Tries (a) wiki by exact meeting_id or title substring;
        falls back to (b) live calendar event for unrecorded scheduled meetings (no summary).

        Use when the user asks 'what was discussed in the Q3 meeting?',
        'summarize my meeting with John', 'recap last week's sync'.

        event_id_or_subject: Graph calendar event id (long), wiki meeting_id (ondrive_*/mock_*),
                             or any substring of the meeting title."""
        if not data_dir:
            return "No data directory available."
        q = (event_id_or_subject or "").strip()
        if not q:
            return "Please provide an event id or subject keyword."
        q_low = q.lower()
        q_norm = normalize_subject(q)

        # (1) Wiki search — exact meeting_id or title substring
        if wiki_dir and wiki_dir.exists():
            try:
                idx = load_index(wiki_dir)
                meetings = idx.get("meetings", {}) or {}
                # Exact meeting_id match
                if q in meetings:
                    full = load_meeting(wiki_dir, q)
                    if full:
                        print(f"[Bot] get_meeting_summary({q}) → wiki exact id")
                        return json.dumps({
                            "source":      "wiki",
                            "meeting_id":  q,
                            "title":       full.get("title", ""),
                            "date":        full.get("date", ""),
                            "summary":     full.get("summary", ""),
                            "decisions":   full.get("decisions", []),
                            "action_items": full.get("action_items", []),
                            "attendee_emails": full.get("attendee_emails", []),
                        }, ensure_ascii=False)
                # Title substring match
                for mid, meta in meetings.items():
                    title = (meta.get("title") or "")
                    title_low = title.lower()
                    if q_low in title_low or (q_norm and q_norm in normalize_subject(title)):
                        full = load_meeting(wiki_dir, mid)
                        if full:
                            print(f"[Bot] get_meeting_summary({q}) → wiki title match {mid}")
                            return json.dumps({
                                "source":      "wiki",
                                "meeting_id":  mid,
                                "title":       full.get("title", ""),
                                "date":        full.get("date", ""),
                                "summary":     full.get("summary", ""),
                                "decisions":   full.get("decisions", []),
                                "action_items": full.get("action_items", []),
                                "attendee_emails": full.get("attendee_emails", []),
                            }, ensure_ascii=False)
            except Exception as e:
                print(f"[Bot] wiki lookup failed: {e}")

        # (2) Calendar fallback — scheduled but unrecorded
        if owner_graph is None:
            return json.dumps({
                "source":  "none",
                "message": f"No wiki meeting matches '{q}', and calendar is not available.",
            }, ensure_ascii=False)
        try:
            now = datetime.now(timezone.utc)
            start = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
            events = owner_graph.get_calendar_view(start, end, top=100)
            # Exact event.id match
            evt = next((e for e in events if e.get("id") == q), None)
            if evt is None:
                # Subject substring match — most recent first
                events_sorted = sorted(
                    events,
                    key=lambda e: (e.get("start") or {}).get("dateTime", ""),
                    reverse=True,
                )
                for e in events_sorted:
                    subj = (e.get("subject") or "")
                    if q_low in subj.lower() or (q_norm and q_norm in normalize_subject(subj)):
                        evt = e
                        break
            if evt:
                print(f"[Bot] get_meeting_summary({q}) → calendar match")
                return json.dumps({
                    "source":   "calendar",
                    "event_id": evt.get("id", ""),
                    "subject":  evt.get("subject", ""),
                    "start":    (evt.get("start") or {}).get("dateTime", ""),
                    "end":      (evt.get("end") or {}).get("dateTime", ""),
                    "attendees": [
                        ((a.get("emailAddress") or {}).get("address") or "")
                        for a in (evt.get("attendees") or [])
                    ],
                    "note": "Meeting has no summary yet — scheduled but not recorded.",
                }, ensure_ascii=False)
        except Exception as e:
            print(f"[Bot] calendar fallback failed: {e}")

        return json.dumps({
            "source":  "none",
            "message": f"No wiki record or calendar event matches '{q}'.",
        }, ensure_ascii=False)

    all_tools = [
        # Query
        get_recent_emails,
        get_upcoming_meetings,
        get_contact_history,
        get_email_frequency_report,
        read_module_result,
        check_email_handling,
        get_meeting_summary,
        search_web,
        # Config
        read_settings,
        update_setting,
        read_skill_instruction,
        update_skill_instruction,
        # Trigger
        run_skill,
        # Action
        mark_commitment_done,
        snooze_commitment,
        dismiss_commitment,
        create_reply_draft,
        list_pending_drafts,
        approve_draft,
        skip_draft,
        confirm_expense,
        discard_expense,
        dismiss_email_followup,
        update_crm_contact,
        create_calendar_event,
        run_outreach,
        tag_recent_contacts,
    ]

    # ── Gemini function calling loop ───────────────────────
    client   = _client()
    contents = list(history) + [types.Content(role="user", parts=[types.Part(text=text)])]
    fn_map   = {f.__name__: f for f in all_tools}

    final_text = ""
    for _ in range(MAX_ROUNDS):
        response = client.models.generate_content(
            model   = MODEL,
            contents= contents,
            config  = types.GenerateContentConfig(
                system_instruction = system,
                tools              = all_tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        candidate  = response.candidates[0] if response.candidates else None
        parts      = (candidate.content.parts if candidate and candidate.content else None) or []
        fn_calls   = [p for p in parts if p.function_call]
        text_parts = [p.text for p in parts if p.text]

        if not fn_calls:
            final_text = "\n".join(t for t in text_parts if t).strip()
            break

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
            response_parts.append(
                types.Part(function_response=types.FunctionResponse(
                    name=fc.name,
                    response={"result": result},
                ))
            )

        contents.append(types.Content(role="model", parts=parts))
        contents.append(types.Content(role="user",  parts=response_parts))

    if not final_text:
        final_text = "Done."

    # Append Outlook draft link if create_reply_draft saved one this turn
    web_link = state.pop("_last_draft_web_link", None)
    if web_link:
        from src.modules.links import wrap_draft_link
        final_text += f"\n\n<a href='{wrap_draft_link(web_link)}'>📬 Open draft in Outlook</a>"

    _save_turn(db_path, text, final_text)
    return final_text, state
