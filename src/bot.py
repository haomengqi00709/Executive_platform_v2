"""
Bot — Gemini function calling orchestrator.

Entry point: reply(state, text, graph, owner_graph, settings, wiki_dir, data_dir, user_model_path)
Returns: (reply_text, updated_state)
"""
import json
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google import genai
from google.genai import types

from src.modules.profile import load_profile_context

MODEL        = "gemini-3.5-flash"
MAX_ROUNDS   = 8
HISTORY_LIMIT = 20

SECTION_IDS = {
    "ai_summary":           "Morning Briefing — daily summary of calendar, emails, priorities, and key relationships",
    "market_intelligence":  "Market Intelligence — current industry news, competitor updates, market trends",
    "company_intelligence": "Company Intelligence — targeted signals on CRM companies, project participants, watchlist (LinkedIn, X, news)",
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
    con = sqlite3.connect(str(db_path))
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
    con = sqlite3.connect(str(db_path))
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
    path.write_text(json.dumps(model, indent=2, ensure_ascii=False))


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
        f"TOOL ROUTING:\n"
        f"  get_recent_emails          → 'show my emails', 'what did X send', 'unread messages'\n"
        f"  get_upcoming_meetings      → 'what meetings do I have', 'who is in my next call'\n"
        f"  get_contact_history        → 'history with X', 'last email from John'\n"
        f"  get_email_frequency_report → 'who do I email most', 'most active contacts'\n"
        f"  read_module_result         → 'what did the briefing say', 'show last email analysis'\n"
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
        f"  run_outreach               → 'draft outreach emails for the people I met at X', 'batch email contacts from OneDrive folder'\n"
        f"                               Always confirm the OneDrive folder and a brief context note with the user first.\n\n"
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
        """Get emails received in the last N hours. Returns subject, sender, received time, preview, is_read, importance."""
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
                    "subject":    m.get("subject", ""),
                    "from":       m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received":   recv[:16],
                    "preview":    (m.get("bodyPreview") or "")[:200],
                    "is_read":    m.get("isRead", True),
                    "importance": m.get("importance", "normal"),
                })
            print(f"[Bot] get_recent_emails({hours_back}h) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def get_upcoming_meetings(hours_ahead: int = 24) -> str:
        """Get calendar meetings in the next N hours. Returns title, start time, end time, attendee emails, location."""
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
                    "title":     e.get("subject", ""),
                    "start":     (e.get("start") or {}).get("dateTime", "")[:16],
                    "end":       (e.get("end") or {}).get("dateTime", "")[:16],
                    "attendees": attendees,
                    "location":  e.get("location", {}).get("displayName", ""),
                })
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
            result = [
                {"email": email, "email_count": count}
                for email, count in counts.most_common(top_n)
            ]
            print(f"[Bot] get_email_frequency_report({days_back}d) → {len(result)} contacts")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"

    def read_module_result(section_id: str) -> str:
        """Read the latest cached result for a section.
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
          company_intelligence — Company Intelligence (targeted signals on CRM/watchlist companies)
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
        body: full plain-text email body in the user's writing style
        IMPORTANT: after this tool succeeds, respond with ONE short sentence only —
        e.g. 'Done, draft saved to your Outlook Drafts.' Do NOT repeat To/Subject/Body.
        Do NOT generate any links or URLs yourself — a link is appended automatically."""
        if owner_graph is None:
            return "Owner account not available."
        try:
            result = owner_graph.create_draft(to=to, subject=subject, body=body)
            web_link = result.get("webLink", "")
            print(f"[Bot] create_reply_draft saved → '{subject}'")
            if web_link:
                state["_last_draft_web_link"] = web_link
            return f"✅ Draft saved to Outlook Drafts: '{subject}' to {to}."
        except Exception as e:
            return f"Error saving draft: {e}"

    def list_pending_drafts() -> str:
        """List all pending email drafts waiting for approval."""
        nonlocal state
        queue   = list(state.get("pending_queue") or [])
        current = state.get("pending_draft")
        if not current and not queue:
            return "No pending drafts."
        items = []
        if current:
            items.append(f"Current: To: {current.get('to','?')} — Subject: {current.get('subject','?')}")
        for i, d in enumerate(queue):
            items.append(f"Queue {i+1}: To: {d.get('to','?')} — Subject: {d.get('subject','?')}")
        return "\n".join(items)

    def approve_draft() -> str:
        """Approve and save the current pending email draft to the user's Outlook Drafts folder."""
        nonlocal state
        draft = state.get("pending_draft")
        if not draft:
            return "No pending draft to approve."
        if owner_graph is None:
            return "Owner account not available."
        try:
            result = owner_graph.create_draft(
                to      = draft.get("to", ""),
                subject = draft.get("subject", ""),
                body    = draft.get("body", ""),
            )
            queue      = list(state.get("pending_queue") or [])
            next_draft = queue[0] if queue else None
            state = {**state, "pending_draft": next_draft, "pending_queue": queue[1:] if queue else []}
            print(f"[Bot] approve_draft → '{draft.get('subject')}'")
            web_link = result.get("webLink", "")
            nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
            if web_link:
                return f"✅ Draft saved — <a href='{web_link}'>Open in Outlook to review and send</a>{nxt}"
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

    def run_outreach(context_note: str = "", folder: str = "") -> str:
        """Batch-generate personalized email drafts from contacts in a OneDrive folder.
        Use after a conference, networking event, or any time the user has a batch of new contacts to reach out to.

        context_note: short context to inject into each draft
                      (e.g. 'met at TechConf 2026', 'introduced by John at the Acme dinner').
                      Always ask the user for this if not obvious from the conversation.
        folder: OneDrive folder path (relative to drive root, e.g. 'Conferences/TechConf').
                Leave empty to use the default from settings (outreach_folder).

        Supported file types: business card photos (jpg/png), PDF rosters, CSV/Excel contact lists.
        Drafts are saved to Outlook Drafts — user manually reviews and sends each one.
        Already-processed files are skipped on re-runs."""
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
            )
            if result.get("status") == "not_run":
                return f"❌ {result.get('error', 'Unknown error')}"
            s = result.get("summary", {})
            msg = (f"✅ Outreach run complete:\n"
                   f"  • {s.get('drafts', 0)} drafts saved to Outlook\n"
                   f"  • {s.get('files', 0)} files processed\n"
                   f"  • {s.get('skipped', 0)} contacts skipped (missing email or generation failed)")
            if s.get("errors", 0):
                msg += f"\n  • {s['errors']} errors"
            return msg
        except Exception as e:
            return f"Error running outreach: {e}"

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

    all_tools = [
        # Query
        get_recent_emails,
        get_upcoming_meetings,
        get_contact_history,
        get_email_frequency_report,
        read_module_result,
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
        final_text += f"\n\n<a href='{web_link}'>📬 Open draft in Outlook</a>"

    _save_turn(db_path, text, final_text)
    return final_text, state
