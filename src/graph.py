import html as _html_mod
import re as _re
import time
import requests
from typing import Any

BASE = "https://graph.microsoft.com/v1.0"


def _fmt_inline(text: str) -> str:
    """HTML-escape text, convert **bold** and [label](url) links."""
    # Extract links before escaping to preserve URLs
    links: list[tuple[str, str]] = _re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', text)
    placeholder_map: dict[str, str] = {}
    for label, url in links:
        placeholder = f"\x00LINK{len(placeholder_map)}\x00"
        placeholder_map[placeholder] = f'<a href="{url}">{_html_mod.escape(label)}</a>'
        text = text.replace(f"[{label}]({url})", placeholder, 1)
    text = _html_mod.escape(text)
    text = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    for placeholder, anchor in placeholder_map.items():
        text = text.replace(_html_mod.escape(placeholder), anchor)
    return text


def _to_teams_html(text: str) -> str:
    """
    Convert plain-text Teams messages (markdown conventions) to Teams-safe HTML.
    Called by send_chat_message — no other files need changing.

      **text**            → <b>text</b>
      • / - / * item      → <ul><li>…</li></ul>  (consecutive items grouped)
        · item (indented) → <ul><li>…</li></ul>
      N. item             → <ol><li>…</li></ol>  (consecutive items grouped)
      blank line          → <br/>
      regular line        → line<br/>
    """
    lines = text.split('\n')
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            out.append('<br/>')
            i += 1
            continue

        # numbered list: "1. text"
        if _re.match(r'^\d{1,2}\.\s+\S', stripped):
            items = []
            while i < len(lines):
                m = _re.match(r'^\d{1,2}\.\s+(.+)$', lines[i].strip())
                if m:
                    items.append(_fmt_inline(m.group(1)))
                    i += 1
                else:
                    break
            out.append('<ol>' + ''.join(f'<li>{it}</li>' for it in items) + '</ol>')
            continue

        # bullet list: "• text", "- text", "* text", or indented "  · text"
        if _re.match(r'^[•\-\*]\s+\S', stripped) or _re.match(r'^\s+[·•]\s+\S', line):
            items = []
            while i < len(lines):
                bm = (_re.match(r'^[•\-\*]\s+(.+)$', lines[i].strip())
                      or _re.match(r'^\s+[·•]\s+(.+)$', lines[i]))
                if bm:
                    items.append(_fmt_inline(bm.group(1)))
                    i += 1
                else:
                    break
            out.append('<ul>' + ''.join(f'<li>{it}</li>' for it in items) + '</ul>')
            continue

        # regular line
        out.append(_fmt_inline(stripped) + '<br/>')
        i += 1

    return ''.join(out)


class GraphClient:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, r, endpoint: str):
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 10))
            print(f"[Graph] Rate limited on {endpoint} — waiting {retry_after}s")
            time.sleep(retry_after)
            raise Exception(f"429 Rate limited: {endpoint}")
        if r.status_code == 401:
            print(f"[Graph] 401 Unauthorized on {endpoint} — token may be expired or revoked")
        r.raise_for_status()
        return r.json()

    def get(self, endpoint: str, params: dict = None, timeout: int = 8) -> dict:
        r = requests.get(f"{BASE}{endpoint}", headers=self.headers, params=params, timeout=timeout)
        return self._handle_response(r, endpoint)

    def post(self, endpoint: str, body: dict = None) -> dict:
        r = requests.post(f"{BASE}{endpoint}", headers=self.headers, json=body, timeout=8)
        return self._handle_response(r, endpoint)

    def post_mime(self, endpoint: str, mime_content: str) -> dict:
        headers = {**self.headers, "Content-Type": "message/rfc822"}
        r = requests.post(f"{BASE}{endpoint}", headers=headers, data=mime_content.encode("utf-8"), timeout=8)
        r.raise_for_status()
        return r.json()

    def delete(self, endpoint: str):
        r = requests.delete(f"{BASE}{endpoint}", headers=self.headers)
        r.raise_for_status()

    def download(self, endpoint: str) -> bytes:
        r = requests.get(f"{BASE}{endpoint}", headers=self.headers, allow_redirects=True)
        r.raise_for_status()
        return r.content

    # ── User ──────────────────────────────────────────────

    def get_me(self) -> dict:
        return self.get("/me")

    def get_mailbox_timezone(self) -> str:
        """Return the user's configured Outlook timezone as a Windows timezone name."""
        try:
            return self.get("/me/mailboxSettings").get("timeZone", "UTC")
        except Exception:
            return "UTC"

    # ── Mail ──────────────────────────────────────────────

    def get_messages(self, top: int = 10, filter: str = None, orderby: str = "receivedDateTime desc",
                     mailbox: str = None, folder: str = None) -> list:
        """Read messages from /me or a delegated mailbox.
        folder: 'Inbox', 'Drafts', 'SentItems', etc. — None means all folders."""
        base = f"/users/{mailbox}" if mailbox else "/me"
        endpoint = f"{base}/mailFolders/{folder}/messages" if folder else f"{base}/messages"
        params = {"$top": top,
                  "$select": "id,subject,from,ccRecipients,receivedDateTime,isRead,importance,hasAttachments,conversationId,bodyPreview,body,webLink"}
        if orderby:
            params["$orderby"] = orderby
        if filter:
            params["$filter"] = filter
        return self.get(endpoint, params=params).get("value", [])

    def get_sent_messages_since(self, days: int = 14, max_results: int = 500) -> list:
        """Fetch sent messages from the past N days, handling pagination."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top":     250,
            "$orderby": "sentDateTime desc",
            "$filter":  f"sentDateTime ge {since}",
            "$select":  "id,subject,conversationId,sentDateTime,toRecipients,bodyPreview",
        }
        results = []
        endpoint = f"{BASE}/me/mailFolders/SentItems/messages"
        while endpoint and len(results) < max_results:
            r = requests.get(endpoint, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            endpoint = data.get("@odata.nextLink")
            params = None
        return results[:max_results]

    def get_inbox_conv_since(self, days: int = 30, max_results: int = 500) -> list:
        """Inbox messages with conversationId — used for reply-needed detection."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top":     250,
            "$orderby": "receivedDateTime desc",
            "$filter":  f"receivedDateTime ge {since}",
            "$select":  "id,subject,from,receivedDateTime,conversationId,bodyPreview",
        }
        results = []
        endpoint = f"{BASE}/me/mailFolders/Inbox/messages"
        while endpoint and len(results) < max_results:
            r = requests.get(endpoint, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            endpoint = data.get("@odata.nextLink")
            params = None
        return results[:max_results]

    def get_flagged_messages(self, days: int = 90) -> list:
        """Messages flagged for follow-up (may include dueDateTime for commitments)."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top":    50,
            "$filter": f"flag/flagStatus eq 'flagged' and receivedDateTime ge {since}",
            "$select": "id,subject,from,receivedDateTime,conversationId,flag",
        }
        r = requests.get(f"{BASE}/me/messages", headers=self.headers, params=params, timeout=8)
        r.raise_for_status()
        return r.json().get("value", [])

    def get_inbox_metadata_since(self, days: int = 180, max_results: int = 2000) -> list:
        """Fetch inbox metadata only (no body) from the past N days — lightweight CRM scan."""
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top":     250,
            "$orderby": "receivedDateTime desc",
            "$filter":  f"receivedDateTime ge {since}",
            "$select":  "id,subject,from,receivedDateTime",
        }
        results = []
        endpoint = f"{BASE}/me/messages"
        while endpoint and len(results) < max_results:
            r = requests.get(endpoint, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            endpoint = data.get("@odata.nextLink")
            params = None
        return results[:max_results]

    def get_messages_since(self, days: int = 30, max_results: int = 500,
                           folder: str = "Inbox") -> list:
        """Fetch messages from the past N days, handling pagination.

        folder: defaults to "Inbox" — restricts to inbox messages only (avoids picking up
                Drafts/Sent/Junk by accident). Pass None to scan all mailbox messages.
        """
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$top":     250,
            "$orderby": "receivedDateTime desc",
            "$filter":  f"receivedDateTime ge {since}",
        }
        results = []
        endpoint = f"{BASE}/me/mailFolders/{folder}/messages" if folder else f"{BASE}/me/messages"
        while endpoint and len(results) < max_results:
            r = requests.get(endpoint, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            endpoint = data.get("@odata.nextLink")
            params = None  # nextLink already contains all params
        return results[:max_results]

    def get_messages_since_datetime(self, since_iso: str, max_results: int = 100) -> list:
        """Fetch messages received after a specific ISO timestamp (for incremental cache)."""
        params = {
            "$top":     100,
            "$orderby": "receivedDateTime desc",
            "$filter":  f"receivedDateTime gt {since_iso}",
        }
        results = []
        endpoint = f"{BASE}/me/messages"
        while endpoint and len(results) < max_results:
            r = requests.get(endpoint, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            endpoint = data.get("@odata.nextLink")
            params = None
        return results[:max_results]

    def get_message(self, message_id: str) -> dict:
        """Fetch a single message with full body. Used by the draft composer
        so AI has the actual email content (reply_needed.json only stores a
        300-char preview)."""
        return self.get(
            f"/me/messages/{message_id}",
            params={"$select": "subject,from,toRecipients,bodyPreview,body,receivedDateTime"},
            timeout=15,
        )

    def create_draft(self, subject: str, body: str, to, mailbox: str = None) -> dict:
        """to can be a single email string or a list of email strings."""
        base = f"/users/{mailbox}" if mailbox else "/me"
        if isinstance(to, str):
            to = [to]
        recipients = [{"emailAddress": {"address": e}} for e in to if e]
        return self.post(f"{base}/messages", {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": recipients,
        })

    def send_mail(self, to: str, subject: str, html: str):
        r = requests.post(
            f"{BASE}/me/sendMail",
            headers=self.headers,
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": html},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                }
            }
        )
        r.raise_for_status()

    def delete_message(self, message_id: str):
        self.delete(f"/me/messages/{message_id}")

    # ── Calendar ──────────────────────────────────────────

    def get_events(self, top: int = 10, filter: str = None) -> list:
        params = {"$top": top, "$orderby": "start/dateTime asc"}
        if filter:
            params["$filter"] = filter
        return self.get("/me/events", params=params).get("value", [])

    def get_calendar_view(self, start_dt: str, end_dt: str, top: int = 20) -> list:
        """Get calendar events in a time window using calendarView (correct way to filter by date range).
        start_dt / end_dt must be ISO-8601 UTC strings, e.g. '2026-05-09T00:00:00Z'.
        """
        params = {
            "startDateTime": start_dt,
            "endDateTime":   end_dt,
            "$top":          top,
            "$orderby":      "start/dateTime asc",
            "$select":       "id,subject,start,end,location,attendees,bodyPreview,isAllDay",
        }
        return self.get("/me/calendarView", params=params).get("value", [])

    # ── OneDrive ──────────────────────────────────────────

    def list_drive_folder(self, path: str) -> list:
        return self.get(f"/me/drive/root:/{path}:/children").get("value", [])

    def search_drive(self, query: str, top: int = 20) -> list:
        return self.get(f"/me/drive/root/search(q='{query}')", {"$top": top}).get("value", [])

    def get_shared_recordings(self, top: int = 50) -> list:
        """Return MP4 files shared with the user (e.g. meeting recordings from other organisers)."""
        try:
            items = self.get("/me/drive/sharedWithMe", {
                "$top": top,
                "$select": "id,name,size,createdDateTime,parentReference,remoteItem,@microsoft.graph.downloadUrl",
            }).get("value", [])
            return [i for i in items if i.get("name", "").endswith(".mp4")]
        except Exception as e:
            print(f"[Graph] sharedWithMe failed: {e}")
            return []

    def download_drive_item(self, item_id: str) -> bytes:
        return self.download(f"/me/drive/items/{item_id}/content")

    def download_shared_item(self, remote_item: dict) -> bytes:
        """Download a shared item, trying multiple Graph API paths."""
        item_id = remote_item.get("id", "")
        remote  = remote_item.get("remoteItem") or {}

        # Path 0: @microsoft.graph.downloadUrl — pre-authenticated URL, bypasses SharePoint auth
        download_url = remote_item.get("@microsoft.graph.downloadUrl")
        if download_url:
            try:
                r = requests.get(download_url, timeout=120)
                r.raise_for_status()
                return r.content
            except Exception as e0:
                print(f"  [shared-dl] downloadUrl path failed: {e0}")

        # Path 1: /me/drive/items/{sharedItemId}/content
        if item_id:
            try:
                return self.download(f"/me/drive/items/{item_id}/content")
            except Exception as e1:
                print(f"  [shared-dl] /me/drive path failed: {e1}")

        # Path 2: /drives/{driveId}/items/{remoteItemId}/content
        drive_id = (remote.get("parentReference", {}).get("driveId") or
                    remote_item.get("parentReference", {}).get("driveId"))
        rid = remote.get("id")
        if drive_id and rid:
            try:
                return self.download(f"/drives/{drive_id}/items/{rid}/content")
            except Exception as e2:
                print(f"  [shared-dl] /drives path failed: {e2}")

        raise ValueError(f"All download paths failed for shared item {item_id}")

    def upload_drive_item(self, folder_path: str, filename: str, content: bytes) -> dict:
        r = requests.put(
            f"{BASE}/me/drive/root:/{folder_path}/{filename}:/content",
            headers={**self.headers, "Content-Type": "application/octet-stream"},
            data=content,
        )
        r.raise_for_status()
        return r.json()

    def ensure_folder_path(self, path: str) -> None:
        """Create nested OneDrive folders if they don't exist. Idempotent."""
        from urllib.parse import quote
        parts = [p for p in path.replace("\\", "/").split("/") if p.strip()]
        for i, part in enumerate(parts):
            current = "/".join(parts[:i + 1])
            encoded = quote(current, safe="/")
            try:
                self.get(f"/me/drive/root:/{encoded}")
                continue  # already exists
            except Exception:
                pass
            if i == 0:
                parent_ep = "/me/drive/root/children"
            else:
                parent_encoded = quote("/".join(parts[:i]), safe="/")
                parent_ep = f"/me/drive/root:/{parent_encoded}:/children"
            try:
                self.post(parent_ep, {"name": part, "folder": {},
                                      "@microsoft.graph.conflictBehavior": "fail"})
            except Exception as e:
                if "409" not in str(e) and "nameAlreadyExists" not in str(e):
                    raise

    def upload_to_onedrive(self, onedrive_path: str, content: bytes, mime: str = "application/octet-stream") -> dict:
        """Upload bytes to an OneDrive path like 'CEO Platform/Receipts/file.jpg'."""
        from urllib.parse import quote
        encoded = quote(onedrive_path, safe="/")
        r = requests.put(
            f"{BASE}/me/drive/root:/{encoded}:/content",
            headers={**self.headers, "Content-Type": mime},
            data=content,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    # ── Online Meetings ───────────────────────────────────

    def get_online_meetings(self, top: int = 10) -> list:
        return self.get("/me/onlineMeetings", {"$top": top}).get("value", [])

    # ── MS To-Do ──────────────────────────────────────────

    def _get_default_todo_list_id(self) -> str:
        """Return the ID of the default To-Do task list."""
        lists = self.get("/me/todo/lists").get("value", [])
        for lst in lists:
            if lst.get("wellknownListName") == "defaultList":
                return lst["id"]
        return lists[0]["id"] if lists else ""

    # ── Teams Chat ────────────────────────────────────────────

    def find_chat_with_user(self, peer_email: str) -> str | None:
        """Find a 1:1 Teams chat with the given user by email. Returns chat ID or None."""
        try:
            data = self.get("/me/chats", {
                "$expand": "members",
                "$filter": "chatType eq 'oneOnOne'",
                "$top": 50,
            })
            for chat in data.get("value", []):
                for member in chat.get("members", []):
                    if member.get("email", "").lower() == peer_email.lower():
                        return chat["id"]
        except Exception:
            pass
        return None

    def get_chat_messages(self, chat_id: str, top: int = 20) -> list:
        """Get recent messages from a Teams chat (newest first)."""
        return self.get(f"/me/chats/{chat_id}/messages", {"$top": top}, timeout=25).get("value", [])

    def send_chat_message(self, chat_id: str, content: str) -> dict:
        """Send a formatted message to a Teams 1:1 chat (plain text auto-converted to HTML)."""
        return self.post(f"/me/chats/{chat_id}/messages", {
            "body": {"contentType": "html", "content": _to_teams_html(content)}
        })

    def send_html_message(self, chat_id: str, html: str) -> dict:
        """Send a raw HTML message to a Teams 1:1 chat. Use when content contains links or pre-built HTML."""
        return self.post(f"/me/chats/{chat_id}/messages", {
            "body": {"contentType": "html", "content": html}
        })

    def create_event(self, subject: str, start: str, end: str,
                     attendees: list = None, location: str = None,
                     timezone: str = "UTC", is_online: bool = False) -> dict:
        """Create a calendar event. start/end are ISO 8601 datetime strings."""
        body: dict = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": timezone},
            "end":   {"dateTime": end,   "timeZone": timezone},
        }
        if attendees:
            body["attendees"] = [
                {"emailAddress": {"address": a.strip()}, "type": "required"}
                for a in attendees if a.strip()
            ]
        if location:
            body["location"] = {"displayName": location}
        if is_online:
            body["isOnlineMeeting"] = True
            body["onlineMeetingProvider"] = "teamsForBusiness"
        return self.post("/me/events", body)

    def create_todo_task(self, title: str, note: str = "", due_date: str = None) -> dict:
        """Create a task in the default To-Do list. due_date format: YYYY-MM-DD."""
        list_id = self._get_default_todo_list_id()
        if not list_id:
            return {}
        body: dict = {
            "title": title,
            "body": {"content": note, "contentType": "text"},
        }
        if due_date:
            body["dueDateTime"] = {"dateTime": f"{due_date}T00:00:00", "timeZone": "UTC"}
        return self.post(f"/me/todo/lists/{list_id}/tasks", body)
