"""
Bot — Gemini 2.5 Pro with native function calling.
Replaces LangGraph StateGraph entirely.

Entry point: reply(state, text, graph, owner_graph, settings, wiki_dir, data_dir)
Returns: (reply_text, updated_state)
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google import genai
from google.genai import types

REPLY_MODEL = "gemini-2.5-pro"
TOOL_MODEL  = "gemini-2.5-flash"
MAX_ROUNDS  = 6
HISTORY_LIMIT = 20


def _client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ── Conversation history (plain SQLite) ───────────────────

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
    contents = []
    for role, content in rows:
        contents.append(types.Content(role=role, parts=[types.Part(text=content)]))
    return contents


def _save_turn(db_path: Path, user_text: str, assistant_text: str):
    con = sqlite3.connect(str(db_path))
    ts = time.time()
    con.execute(
        "INSERT INTO history (role, content, ts) VALUES (?, ?, ?)",
        ("user", user_text, ts),
    )
    con.execute(
        "INSERT INTO history (role, content, ts) VALUES (?, ?, ?)",
        ("model", assistant_text, ts + 0.001),
    )
    con.commit()
    con.close()


# ── Core reply function ───────────────────────────────────

def reply(
    state: dict,
    text: str,
    graph,
    owner_graph,
    settings: dict,
    wiki_dir: Path,
    data_dir: Path,
) -> tuple[str, dict]:
    db_path = data_dir / "bot_history.db"
    history = _load_history(db_path)

    # ── System prompt ──────────────────────────────────────
    display_name     = settings.get("display_name", "the executive")
    business_context = settings.get("business_context", "")
    timezone_str     = settings.get("timezone", "UTC")
    now_str          = datetime.now(timezone.utc).strftime("%A, %B %d, %Y %H:%M UTC")
    bc_line          = f"\n\nBusiness context: {business_context}" if business_context else ""

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
        f"Today: {now_str}. Timezone: {timezone_str}.\n\n"
        f"Be concise, professional, and action-oriented. Use bullet points for lists.\n"
        f"When asked about emails, meetings, or contacts — always call the relevant tool first. "
        f"Never invent data. Respond in the same language the user writes in."
        f"{pending_note}"
    )

    # ── Tool definitions ───────────────────────────────────

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

    def search_web(query: str) -> str:
        """Search the web for current news, market data, or any information not in the user's inbox/calendar."""
        try:
            client = _client()
            resp   = client.models.generate_content(
                model=TOOL_MODEL,
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

    def list_pending_drafts() -> str:
        """List all pending email drafts waiting for approval."""
        nonlocal state
        queue = list(state.get("pending_queue") or [])
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
            queue = list(state.get("pending_queue") or [])
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
        queue = list(state.get("pending_queue") or [])
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
        get_recent_emails,
        get_upcoming_meetings,
        get_contact_history,
        search_web,
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
            model   = REPLY_MODEL,
            contents= contents,
            config  = types.GenerateContentConfig(
                system_instruction = system,
                tools              = all_tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        candidate = response.candidates[0] if response.candidates else None
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
