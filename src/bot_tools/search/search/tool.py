"""Unified read-only search across the user's data. One LLM-facing entry point
(`what` selects the domain); each domain backend is deterministic code — the AI fills
semantic parameters, code builds the API call. Results register into the existing
addressable list types ("emails"/"contacts"/"meetings") so #N follow-ups (open 2,
reply to 1) keep working on search results."""
import json
from datetime import datetime, timedelta, timezone

IS_ACTION = False

_DOMAINS = ("emails", "attachments", "contacts", "meetings", "files")


def _contact_tokens_match(query: str, c: dict) -> bool:
    """Every query token must appear somewhere in name/email/company — any order,
    so 'jason hao' matches 'Hao Jason' (raw substring matching couldn't)."""
    hay = " ".join([
        (c.get("name") or ""), (c.get("email") or ""), (c.get("company") or ""),
        (c.get("role") or ""),
    ]).lower()
    toks = [t for t in query.lower().split() if t]
    return bool(toks) and all(t in hay for t in toks)


def build(ctx):
    def search(what: str, query: str, days_back: int = 0, top: int = 10) -> str:
        from src.bot import _with_indices, _register_list
        what = (what or "").strip().lower()
        query = (query or "").strip()
        if what not in _DOMAINS:
            return f"Unknown search domain '{what}'. Use one of: {', '.join(_DOMAINS)}."
        if not query:
            return "Need a search query — what should I look for?"
        top = min(max(int(top or 10), 1), 15)

        try:
            # ── emails / attachments: Exchange full-mailbox search index ──
            if what in ("emails", "attachments"):
                graph = ctx.owner_graph
                if graph is None:
                    return "Owner account not available."
                kql = f"attachment:{query}" if what == "attachments" else query
                msgs = graph.search_messages(kql, top=top)
                if days_back:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))
                    def _keep(m):
                        try:
                            return datetime.fromisoformat(
                                m.get("receivedDateTime", "").replace("Z", "+00:00")) >= cutoff
                        except Exception:
                            return True
                    msgs = [m for m in msgs if _keep(m)]
                result = [{
                    "email_id":        m.get("id", ""),
                    "subject":         m.get("subject", ""),
                    "from":            m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received":        m.get("receivedDateTime", "")[:16],
                    "preview":         (m.get("bodyPreview") or "")[:200],
                    "has_attachments": m.get("hasAttachments", False),
                } for m in msgs[:top]]
                if not result:
                    return (f"No emails matched '{query}' in the full mailbox search. "
                            f"Tell the user honestly — do not guess.")
                result = _with_indices(result)
                _register_list(ctx, "emails", result, "email_id",
                               label_fn=lambda it: f'{it.get("from","")} — "{(it.get("subject") or "")[:50]}"',
                               source=f"search:{what} {query}")
                print(f"[Bot] search({what}, {query!r}) → {len(result)}")
                return json.dumps(result, ensure_ascii=False)

            # ── contacts: local CRM, token-based matching (any word order) ──
            if what == "contacts":
                if not ctx.data_dir:
                    return "No data directory available."
                from src.modules.crm import load_crm
                crm = load_crm(ctx.data_dir)
                matches = []
                for email, c in (crm.get("contacts") or {}).items():
                    row = {
                        "email":   c.get("email") or email,
                        "name":    c.get("name") or "",
                        "company": c.get("company") or "",
                        "role":    c.get("role") or "",
                    }
                    if _contact_tokens_match(query, row):
                        matches.append(row)
                matches = matches[:top]
                if not matches:
                    return f"No CRM contact matched '{query}'. Ask the user for the email address."
                matches = _with_indices(matches)
                _register_list(ctx, "contacts", matches, "email",
                               label_fn=lambda it: f'{it.get("name","")} — {it.get("company","")} <{it.get("email","")}>',
                               source=f"search:contacts {query}")
                print(f"[Bot] search(contacts, {query!r}) → {len(matches)}")
                return json.dumps(matches, ensure_ascii=False)

            # ── meetings: calendar window (past 180d + next 90d), code-side match ──
            if what == "meetings":
                graph = ctx.owner_graph
                if graph is None:
                    return "Owner account not available."
                now = datetime.now(timezone.utc)
                back = int(days_back) if days_back else 180
                events = graph.get_calendar_view(
                    start_dt=(now - timedelta(days=back)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    end_dt=(now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    top=250,
                )
                toks = [t for t in query.lower().split() if t]
                result = []
                for e in events:
                    attendees = [a.get("emailAddress", {}).get("address", "")
                                 for a in (e.get("attendees") or [])]
                    hay = " ".join([e.get("subject") or "",
                                    (e.get("bodyPreview") or "")[:200],
                                    " ".join(attendees)]).lower()
                    if all(t in hay for t in toks):
                        result.append({
                            "event_id":  e.get("id", ""),
                            "title":     e.get("subject", ""),
                            "start":     (e.get("start") or {}).get("dateTime", "")[:16],
                            "attendees": attendees,
                            "location":  e.get("location", {}).get("displayName", ""),
                        })
                result = result[-top:]   # most recent of the window
                if not result:
                    return f"No calendar events matched '{query}' in the last {back} days or upcoming 90."
                result = _with_indices(result)
                _register_list(ctx, "meetings", result, "event_id",
                               label_fn=lambda it: f'{it.get("title","")} ({it.get("start","")})',
                               source=f"search:meetings {query}")
                print(f"[Bot] search(meetings, {query!r}) → {len(result)}")
                return json.dumps(result, ensure_ascii=False)

            # ── files: OneDrive search index ──
            graph = ctx.owner_graph
            if graph is None:
                return "Owner account not available."
            items = graph.search_drive(query, top=top)
            result = [{
                "file_id":  i.get("id", ""),
                "name":     i.get("name", ""),
                "modified": (i.get("lastModifiedDateTime") or "")[:16],
                "size_kb":  round((i.get("size") or 0) / 1024),
                "web_url":  i.get("webUrl", ""),
            } for i in items[:top]]
            if not result:
                return f"No OneDrive files matched '{query}'."
            result = _with_indices(result)
            _register_list(ctx, "files", result, "file_id",
                           label_fn=lambda it: f'{it.get("name","")} ({it.get("modified","")})',
                           source=f"search:files {query}")
            print(f"[Bot] search(files, {query!r}) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)

        except Exception as e:
            return f"Search error: {e}"
    return search
