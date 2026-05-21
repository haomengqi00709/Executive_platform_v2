# Auth + Graph API — Foundation Guide

This folder is the clean v2 foundation. It contains the proven auth and Graph API connection code extracted from v1, with all business logic stripped out.

With this you can:
1. Log in via Microsoft (OAuth web flow or device code for local dev)
2. Get a valid access token that auto-refreshes
3. Call any Microsoft Graph API endpoint (mail, calendar, OneDrive, Teams)

---

## 1. Azure AD App Registration

You need an app registration in Azure AD (Entra ID). The v1 app is already registered — use those credentials.

If creating a new one:
1. Go to [portal.azure.com](https://portal.azure.com) → Azure Active Directory → App registrations → New registration
2. Name: anything (e.g. "CEO Platform v2")
3. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts** (multi-tenant)
4. Redirect URI: Web → `http://localhost:8000/auth/callback`
5. After creation, go to **Certificates & secrets** → New client secret → copy the value
6. Copy the **Application (client) ID** from the Overview page

Add these redirect URIs under Authentication → Add a platform → Web:
- `http://localhost:8000/auth/callback` (local dev)
- `https://your-railway-domain.up.railway.app/auth/callback` (production)

---

## 2. Required Permissions (Scopes)

These are delegated permissions — the user grants them at login time. No admin consent needed for most.

| Permission | Used for |
|---|---|
| `Mail.Read` / `Mail.ReadWrite` / `Mail.Send` | Read inbox, create drafts |
| `Calendars.Read` / `Calendars.ReadWrite` | Read calendar events |
| `Files.Read` / `Files.Read.All` / `Files.ReadWrite` | Read/write OneDrive files |
| `Sites.Read.All` | SharePoint / Teams shared files |
| `User.Read` | Get logged-in user's profile |
| `Tasks.ReadWrite` | Microsoft To-Do tasks |
| `Chat.ReadWrite` | Send/receive Teams chat messages |
| `MailboxSettings.Read` | Read timezone setting |

---

## 3. Local Setup

```bash
cd CEO_platform_v2
pip install -r requirements.txt
cp .env.example .env
# Edit .env — fill in PROD_CLIENT_ID and PROD_CLIENT_SECRET
uvicorn src.server:app --reload --port 8000
```

---

## 4. OAuth Login Flow

```
User visits /auth/login
    ↓
Server generates state nonce, builds Azure AD URL, redirects user
    ↓
User logs in at Microsoft (or is already logged in)
    ↓
Microsoft redirects to /auth/callback?code=...
    ↓
Server exchanges code → gets access_token + refresh_token
    ↓
Tokens saved to .data/_sessions/{user_id}.json
JWT cookie set (httponly, 7-day, HS256)
    ↓
User redirected to /
```

After login, every request to protected endpoints includes the JWT cookie automatically. The server decodes it to get `user_id`, loads the token, and calls Graph API.

---

## 5. JWT Session

- Algorithm: HS256
- Expiry: 7 days (stateless — survives server restarts)
- Cookie: `session_token`, httponly, samesite=lax
- Payload: `{ user_id, username, exp, iat }`

The `SESSION_SECRET` env var signs and verifies the JWT. Keep it secret and random in production.

---

## 6. Token Storage

Tokens are stored per-user at `.data/_sessions/{user_id}.json`:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "0.A...",
  "expiry": "2026-05-21T14:30:00+00:00",
  "username": "user@example.com"
}
```

`get_valid_access_token(user_id)` handles refresh automatically:
1. If token is still valid (>5 min remaining) → return it immediately
2. If expired → use `refresh_token` to get a new one from Microsoft
3. If no refresh_token → fall back to MSAL cache (device-flow accounts)

On Railway, `.data/` is a mounted volume — tokens persist across deploys.

---

## 7. GraphClient Usage

```python
from src import auth
from src.graph import GraphClient

# In any FastAPI route:
@app.get("/api/my-endpoint")
def my_endpoint(session: dict = Depends(require_session)):
    uid   = session["user_id"]
    token = auth.get_valid_access_token(uid)  # auto-refreshes
    graph = GraphClient(token)

    # Read inbox
    emails = graph.get_messages(top=10)

    # Read calendar (ALWAYS use get_calendar_view, not get_events with filter)
    from datetime import datetime, timedelta, timezone
    now   = datetime.now(timezone.utc)
    end   = now + timedelta(hours=24)
    events = graph.get_calendar_view(
        start_dt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Send a Teams message
    chat_id = graph.find_chat_with_user("someone@example.com")
    if chat_id:
        graph.send_chat_message(chat_id, "Hello from the API!")

    # Create a draft email (never send directly — always save to Drafts)
    graph.create_draft(
        subject="Re: your message",
        body="<p>Thanks for reaching out...</p>",
        to="someone@example.com",
    )

    return {"ok": True}
```

---

## 8. Test the Chain

After starting the server and logging in:

```
GET http://localhost:8000/api/test/graph
```

Returns:
```json
{
  "ok": true,
  "user": {
    "displayName": "Daniel CEO",
    "mail": "daniel@company.com"
  },
  "latest_emails": [
    { "subject": "Q2 Review", "from": "cfo@company.com", "received": "2026-05-21 09:00" }
  ]
}
```

If you see `"ok": true` here, the entire auth → token refresh → Graph API chain is working.

---

## 9. Gotchas from v1 (Do NOT repeat)

| Issue | Wrong way | Correct way |
|---|---|---|
| Calendar date-range queries | `get_events(filter="start/dateTime ge ...")` — silently returns wrong results | `get_calendar_view(start_dt=..., end_dt=...)` |
| Multi-tenant authority | `https://login.microsoftonline.com/{tenant_id}` — only works for that tenant | `https://login.microsoftonline.com/common` — works for all M365 + personal accounts |
| Teams Adaptive Card separator | `{"type": "Separator"}` — Teams silently drops the entire card | `"separator": true` on the **next** element |
| Teams Action type | `Action.ToggleVisibility` — not supported via webhook | Use `Action.OpenUrl` or `Action.Submit` |
| Draft emails | Calling `send_mail()` directly | Always save to Drafts first; user approves before sending |
| Token refresh timing | Refresh only after 401 | Refresh 5 minutes before expiry (proactive) |
| Railway filesystem | Storing user data in a non-mounted path — resets on deploy | Mount `.data/` as a Railway volume |

---

## 10. Adding New Routes

This is the pattern for all new API routes:

```python
from src import auth
from src.graph import GraphClient
from src.server import require_session  # or copy the dependency

@app.get("/api/my-feature")
def my_feature(session: dict = Depends(require_session)):
    uid   = session["user_id"]
    token = auth.get_valid_access_token(uid)
    graph = GraphClient(token)

    # do things with graph...
    return {"data": ...}
```

To add a Teams bot (like Audrey in v1):
1. Register a second M365 account (the bot account)
2. Have it log in via the web OAuth flow
3. Store its `user_id` in a config file linking it to the owner's `user_id`
4. Use the bot's token to call `graph.find_chat_with_user()` and `graph.send_chat_message()`
5. Poll `graph.get_chat_messages()` on an interval to receive incoming messages
