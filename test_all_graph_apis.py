"""
Graph API field survey — runs real API calls, prints actual field shapes.
Output is sanitized: email addresses are masked (user@domain → u***@domain).
Run: python test_all_graph_apis.py
Results are written to API_DATA_REFERENCE.md
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Point to v1's .data so we reuse existing tokens
V1_DATA = Path(__file__).parent.parent / ".data"
os.environ.setdefault("DATA_DIR", str(V1_DATA))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
load_dotenv(Path(__file__).parent / ".env", override=False)

sys.path.insert(0, str(Path(__file__).parent))
from src.auth import load_user_tokens, get_valid_access_token
from src.graph import GraphClient


# ── Sanitize helpers ──────────────────────────────────────

def _mask_email(addr: str) -> str:
    if "@" not in addr:
        return addr
    local, domain = addr.split("@", 1)
    return local[:2] + "***@" + domain

def _sanitize(obj, depth=0):
    """Recursively mask email addresses and truncate long strings."""
    if depth > 10:
        return obj
    if isinstance(obj, str):
        obj = re.sub(r'[\w.+-]+@[\w.-]+\.\w+',
                     lambda m: _mask_email(m.group()), obj)
        if len(obj) > 300:
            return obj[:300] + "…[truncated]"
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v, depth+1) for k, v in obj.items()
                if k not in ("body", "@odata.etag")}  # skip full body and odata noise
    if isinstance(obj, list):
        return [_sanitize(i, depth+1) for i in obj[:3]]  # first 3 items only
    return obj


# ── Output builder ────────────────────────────────────────

sections: list[str] = []

def report(title: str, method_name: str, items, error: str = None):
    lines = [f"## {title}", f"**Method:** `{method_name}`", ""]
    if error:
        lines += [f"**ERROR:** {error}", ""]
    elif not items:
        lines += ["_No results returned (empty list or None)_", ""]
    else:
        sample = items[0] if isinstance(items, list) else items
        sanitized = _sanitize(sample)
        lines += [
            f"**Fields returned ({len(items) if isinstance(items, list) else 1} total):**",
            "```json",
            json.dumps(sanitized, indent=2, default=str),
            "```",
            "",
            f"**All keys:** `{', '.join(sanitized.keys() if isinstance(sanitized, dict) else [])}`",
            "",
        ]
    sections.append("\n".join(lines))
    print(f"  {'OK' if not error else 'ERR'} — {title}")


# ── Main ─────────────────────────────────────────────────

def find_user_id() -> str:
    sessions_dir = V1_DATA / "_sessions"
    if not sessions_dir.exists():
        raise Exception(f"No sessions dir at {sessions_dir}")
    files = list(sessions_dir.glob("*.json"))
    if not files:
        raise Exception("No session files found")
    # Prefer the non-bot user (bot has is_registered_bot flag)
    for f in files:
        try:
            data = json.loads(f.read_text())
            if not data.get("is_registered_bot"):
                return f.stem
        except Exception:
            pass
    return files[0].stem


def main():
    print("Finding authenticated user…")
    user_id = find_user_id()
    print(f"Using user_id: {user_id}")

    token = get_valid_access_token(user_id)
    g = GraphClient(token)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    # ── User ─────────────────────────────────────────────
    print("\n[User]")
    try:
        me = g.get_me()
        report("get_me()", "get_me()", me)
    except Exception as e:
        report("get_me()", "get_me()", None, str(e))

    try:
        tz = g.get_mailbox_timezone()
        report("get_mailbox_timezone()", "get_mailbox_timezone()", {"timezone": tz})
    except Exception as e:
        report("get_mailbox_timezone()", "get_mailbox_timezone()", None, str(e))

    # ── Email ─────────────────────────────────────────────
    print("\n[Email]")
    try:
        msgs = g.get_messages(top=2)
        report("get_messages(top=2) — full body included", "get_messages(top)", msgs)
    except Exception as e:
        report("get_messages(top=2)", "get_messages(top)", None, str(e))

    try:
        msgs = g.get_inbox_conv_since(days=7)
        report("get_inbox_conv_since(days=7) — $select fields", "get_inbox_conv_since(days)", msgs)
    except Exception as e:
        report("get_inbox_conv_since(days=7)", "get_inbox_conv_since(days)", None, str(e))

    try:
        msgs = g.get_sent_messages_since(days=7)
        report("get_sent_messages_since(days=7)", "get_sent_messages_since(days)", msgs)
    except Exception as e:
        report("get_sent_messages_since(days=7)", "get_sent_messages_since(days)", None, str(e))

    try:
        msgs = g.get_flagged_messages(days=90)
        report("get_flagged_messages(days=90) — flag object", "get_flagged_messages(days)", msgs)
    except Exception as e:
        report("get_flagged_messages(days=90)", "get_flagged_messages(days)", None, str(e))

    try:
        msgs = g.get_inbox_metadata_since(days=30)
        report("get_inbox_metadata_since(days=30) — lightweight, 4 fields", "get_inbox_metadata_since(days)", msgs)
    except Exception as e:
        report("get_inbox_metadata_since(days=30)", "get_inbox_metadata_since(days)", None, str(e))

    # Attachments — fetch a message with attachments and show structure
    print("\n[Attachments]")
    try:
        msgs_with_att = [m for m in g.get_messages(top=50) if m.get("hasAttachments")]
        if msgs_with_att:
            msg_id = msgs_with_att[0]["id"]
            r = g.get(f"/me/messages/{msg_id}/attachments", {"$top": 3})
            atts = r.get("value", [])
            report("message attachments — /me/messages/{id}/attachments", "get('/me/messages/{id}/attachments')", atts)
        else:
            report("message attachments", "get('/me/messages/{id}/attachments')", None,
                   "No messages with attachments found in top 50")
    except Exception as e:
        report("message attachments", "get('/me/messages/{id}/attachments')", None, str(e))

    # ── Calendar ─────────────────────────────────────────
    print("\n[Calendar]")
    try:
        events = g.get_calendar_view(today, tomorrow, top=10)
        report("get_calendar_view(today, tomorrow) — today's meetings", "get_calendar_view(start, end)", events)
    except Exception as e:
        report("get_calendar_view(today, tomorrow)", "get_calendar_view(start, end)", None, str(e))

    # ── OneDrive ─────────────────────────────────────────
    print("\n[OneDrive]")
    try:
        results = g.search_drive("mp4", top=5)
        report("search_drive('mp4') — drive item structure", "search_drive(query)", results)
    except Exception as e:
        report("search_drive('mp4')", "search_drive(query)", None, str(e))

    try:
        recordings = g.get_shared_recordings(top=5)
        report("get_shared_recordings() — shared .mp4 files", "get_shared_recordings()", recordings)
    except Exception as e:
        report("get_shared_recordings()", "get_shared_recordings()", None, str(e))

    try:
        root = g.get(f"/me/drive/root/children", {"$top": 3, "$select": "id,name,size,createdDateTime,folder,file"})
        items = root.get("value", [])
        report("OneDrive root children — folder/file item structure", "list_drive_folder('root')", items)
    except Exception as e:
        report("OneDrive root children", "list_drive_folder('root')", None, str(e))

    # ── MS To-Do ─────────────────────────────────────────
    print("\n[MS To-Do]")
    try:
        lists_r = g.get("/me/todo/lists", {"$top": 5})
        todo_lists = lists_r.get("value", [])
        report("To-Do lists — /me/todo/lists", "get('/me/todo/lists')", todo_lists)
    except Exception as e:
        report("To-Do lists", "get('/me/todo/lists')", None, str(e))

    # ── Teams Chat ───────────────────────────────────────
    print("\n[Teams Chat]")
    try:
        chats_r = g.get("/me/chats", {"$filter": "chatType eq 'oneOnOne'", "$top": 3, "$expand": "members", "$select": "id,chatType"})
        chats = chats_r.get("value", [])
        report("Teams 1:1 chats — /me/chats", "find_chat_with_user()", chats)
    except Exception as e:
        report("Teams 1:1 chats", "find_chat_with_user()", None, str(e))

    # ── Write output ─────────────────────────────────────
    out_path = Path(__file__).parent / "API_DATA_REFERENCE.md"
    header = f"""# Graph API Data Reference

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Email addresses are masked (us***@domain.com).

This document shows the **actual fields returned** by each Graph API method,
based on a live test against a real M365 account.
Used to design the v2 context layer (what data gets fed to AI).

---

"""
    out_path.write_text(header + "\n\n---\n\n".join(sections))
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
