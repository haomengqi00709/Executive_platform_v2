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

MODEL        = "gemini-3.5-flash"
MAX_ROUNDS   = 8
HISTORY_LIMIT = 20

SKILL_NAMES = {
    "morning_briefing":    "Morning Briefing (M01)",
    "email_intelligence":  "Email Intelligence (M02)",
    "meeting_intelligence":"Meeting Intelligence (M03)",
    "business_insights":   "Business Insights (M04)",
    "expense_capture":     "Expense Capture (M05)",
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
    """Read cached module results and return a short status summary for the system prompt.
    Zero API cost — silently skips any missing or malformed files."""
    lines = []
    try:
        m02 = json.loads((data_dir / "results" / "m02.json").read_text())
        reply    = m02.get("reply_needed", [])
        followup = m02.get("followup_needed", [])
        if reply:
            oldest = reply[0]
            lines.append(
                f"Reply needed: {len(reply)} emails"
                f" — oldest: \"{oldest.get('subject','')}\" from {oldest.get('from','')} ({oldest.get('days_waiting',0)}d)"
            )
        if followup:
            lines.append(f"Follow-up needed: {len(followup)} sent emails with no response")
    except Exception:
        pass
    try:
        m03 = json.loads((data_dir / "results" / "m03.json").read_text())
        open_items = [a for a in (m03.get("action_items") or []) if not a.get("completed")]
        if open_items:
            lines.append(f"Open meeting action items: {len(open_items)} unresolved")
    except Exception:
        pass
    try:
        m04 = json.loads((data_dir / "results" / "m04.json").read_text())
        at_risk = [c for c in (m04.get("contacts") or []) if c.get("status") in ("at_risk", "dormant")][:3]
        if at_risk:
            names = ", ".join(c.get("name") or c.get("email", "") for c in at_risk)
            lines.append(f"Relationship alerts: {names}")
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
    business_context = settings.get("business_context", "")
    timezone_str     = settings.get("timezone", "UTC")
    now_str          = datetime.now(timezone.utc).strftime("%A, %B %d, %Y %H:%M UTC")
    bc_line          = f"\n\nBusiness context: {business_context}" if business_context else ""

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
            f"If the user says approve/yes/send/ok → call approve_draft(). "
            f"If they say skip/no/dismiss → call skip_draft()."
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
        f"You are an AI executive assistant for {display_name}.{bc_line}\n\n"
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
        f"  read_skill_instruction     → 'how is briefing configured', 'show skill for X'\n"
        f"  update_skill_instruction   → 'make briefing more concise', 'change skill behavior'\n"
        f"  run_skill                  → 'run morning briefing now', 'trigger email analysis'\n"
        f"  dismiss_item               → 'ignore this', 'skip X', 'don't show me this again'\n"
        f"  approve_draft / skip_draft → only when a pending draft is shown above\n"
        f"  confirm_expense / discard_expense → only when a pending expense is shown above"
        f"{user_ctx}"
        f"{session_ctx}"
        f"{pending_note}"
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

    def read_module_result(module_name: str) -> str:
        """Read the latest cached result for a module. module_name must be one of: m01, m02, m03, m04, m05."""
        valid = {"m01", "m02", "m03", "m04", "m05"}
        if module_name not in valid:
            return f"Invalid module name. Use one of: {', '.join(sorted(valid))}"
        result_path = data_dir / "results" / f"{module_name}.json"
        if not result_path.exists():
            return f"No results for {module_name} yet. Run the skill first with run_skill()."
        try:
            data = json.loads(result_path.read_text())
            print(f"[Bot] read_module_result({module_name})")
            return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return f"Error reading {module_name}: {e}"

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
        Top-level keys include: display_name, business_context, timezone, check_interval_hours.
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
        briefing_style (string). Pass lists/dicts as JSON strings, e.g. '["a@b.com"]'."""
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

    def read_skill_instruction(skill_name: str) -> str:
        """Read the instruction/configuration for a specific skill.
        skill_name must be one of: morning_briefing, email_intelligence, meeting_intelligence, business_insights, expense_capture."""
        if skill_name not in SKILL_NAMES:
            return f"Unknown skill. Available: {', '.join(SKILL_NAMES)}"
        skill_path = data_dir / "skills" / f"{skill_name}.md"
        if not skill_path.exists():
            return f"No instruction file for '{skill_name}' yet. Use update_skill_instruction to create one."
        print(f"[Bot] read_skill_instruction({skill_name})")
        return skill_path.read_text()

    def update_skill_instruction(skill_name: str, content: str) -> str:
        """Update (overwrite) the instruction file for a specific skill. The content is a markdown document
        describing how the skill should behave. skill_name must be one of: morning_briefing, email_intelligence,
        meeting_intelligence, business_insights, expense_capture."""
        if skill_name not in SKILL_NAMES:
            return f"Unknown skill. Available: {', '.join(SKILL_NAMES)}"
        skill_dir = data_dir / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / f"{skill_name}.md").write_text(content)
        print(f"[Bot] update_skill_instruction({skill_name}) → {len(content)} chars")
        return f"✅ Skill instruction updated: {skill_name}"

    # --- Trigger tool ---

    def run_skill(skill_name: str) -> str:
        """Trigger a skill to run immediately in the background. Results appear in the dashboard when done.
        skill_name must be one of: morning_briefing, email_intelligence, meeting_intelligence, business_insights, expense_capture."""
        if skill_name not in SKILL_NAMES:
            return f"Unknown skill. Available: {', '.join(SKILL_NAMES)}"

        MODULE_MAP = {
            "morning_briefing":    "src.modules.m01_briefing",
            "email_intelligence":  "src.modules.m02_email",
            "meeting_intelligence":"src.modules.m03_meeting",
            "business_insights":   "src.modules.m04_intelligence",
            "expense_capture":     "src.modules.m05_expense",
        }

        def _run():
            import importlib
            try:
                mod = importlib.import_module(MODULE_MAP[skill_name])
                mod.run(owner_graph=owner_graph, data_dir=data_dir, settings=settings)
            except ModuleNotFoundError:
                print(f"[Bot] run_skill: {MODULE_MAP[skill_name]} not yet implemented")
            except Exception as e:
                print(f"[Bot] run_skill {skill_name} error: {e}")

        import threading
        threading.Thread(target=_run, daemon=True).start()
        print(f"[Bot] run_skill({skill_name}) → started")
        return f"✅ {SKILL_NAMES[skill_name]} is running. Results will appear in your dashboard shortly."

    # --- Action tools ---

    def dismiss_item(subject_hint: str) -> str:
        """Permanently suppress an email or item so it no longer appears in action items or briefings.
        subject_hint: partial subject line, sender name, or any keyword identifying the item."""
        nonlocal user_model
        skipped = list(user_model.get("skipped_items", []))
        skipped.append({
            "hint":       subject_hint,
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
        })
        user_model = {**user_model, "skipped_items": skipped}
        _save_user_model(user_model_path, user_model)
        print(f"[Bot] dismiss_item({subject_hint!r})")
        return f"✅ Dismissed — '{subject_hint}' will no longer appear in briefings or action items."

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
            owner_graph.create_draft(
                to      = draft.get("to", ""),
                subject = draft.get("subject", ""),
                body    = draft.get("body", ""),
            )
            queue      = list(state.get("pending_queue") or [])
            next_draft = queue[0] if queue else None
            state = {**state, "pending_draft": next_draft, "pending_queue": queue[1:] if queue else []}
            print(f"[Bot] approve_draft → '{draft.get('subject')}'")
            nxt = f"\n\nNext draft ready: '{next_draft.get('subject')}'" if next_draft else ""
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
            if hashes_file and pending.get("hash"):
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
        dismiss_item,
        list_pending_drafts,
        approve_draft,
        skip_draft,
        confirm_expense,
        discard_expense,
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

    _save_turn(db_path, text, final_text)
    return final_text, state
