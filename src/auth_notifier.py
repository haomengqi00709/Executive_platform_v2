"""
Watches per-user auth health. When status flips healthy→broken, sends ONE
English email to the affected user explaining what happened and how to fix it.

Spam protection:
  - Email #1 sent immediately on flip to broken
  - Email #2 sent 7 days later IF still broken
  - That's it — no more emails (recovery resets the counter)

Sender selection (the broken account can't send its own alert):
  - Bot broken     → use owner's token to send the alert
  - Owner broken   → use bot's token to send the alert
  - Both broken    → log to dead-letter, no email sent
"""

import json
import os
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import auth
from src.auth_errors import classify_aadsts
from src.graph import GraphClient


REMINDER_AFTER_DAYS = 7
MAX_EMAILS = 2

_app_url = os.getenv("APP_URL") or os.getenv("REDIRECT_URI", "").rsplit("/auth/", 1)[0]
if not _app_url:
    raise RuntimeError(
        "auth_notifier requires APP_URL or REDIRECT_URI env var "
        "(emails to users about broken sign-in need a real reconnect link, "
        "not a placeholder)."
    )
APP_URL = _app_url.rstrip("/")
RECONNECT_PATH = "/#settings"  # Settings page hosts the AI Assistant reconnect UI

def _dead_letter_path(broken_uid: str) -> Path:
    return auth.user_data_dir(broken_uid) / ".auth_notifier_deadletter.log"


def _log_dead_letter(broken_uid: str, line: str):
    """Records an undeliverable notification for the broken account. Per-user
    file so we can pull one user's dead-letter history via the admin diag endpoint."""
    try:
        path = _dead_letter_path(broken_uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}  {line}\n")
    except Exception:
        pass


def _bot_state(user_id: str) -> dict | None:
    p = auth.DATA_DIR / user_id / "teams_bot.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _is_bot(user_id: str) -> bool:
    s = _bot_state(user_id)
    return bool(s and s.get("is_registered_bot"))


def _owner_of_bot(bot_uid: str) -> str | None:
    s = _bot_state(bot_uid)
    return s.get("owner_uid") if s else None


def _find_bot_owned_by(owner_uid: str) -> str | None:
    sessions_dir = auth.DATA_DIR / "_sessions"
    if not sessions_dir.exists():
        return None
    for tf in sessions_dir.glob("*.json"):
        bid = tf.stem
        if bid == owner_uid:
            continue
        s = _bot_state(bid)
        if s and s.get("owner_uid") == owner_uid and s.get("is_registered_bot"):
            return bid
    return None


def _account_email(user_id: str) -> str | None:
    tokens = auth.load_user_tokens(user_id) or {}
    return tokens.get("username")


def _account_label(user_id: str) -> str:
    """Human-readable name for the account in email body."""
    email = _account_email(user_id) or user_id
    if _is_bot(user_id):
        return f"your AI assistant ({email})"
    return f"your Microsoft account ({email})"


def _pick_sender_uid(broken_uid: str) -> str | None:
    """Pick another account whose token still works, to send the alert from.
    Try in this order: owner→bot, or bot→owner."""
    candidates: list[str] = []
    if _is_bot(broken_uid):
        owner = _owner_of_bot(broken_uid)
        if owner:
            candidates.append(owner)
    else:
        bot = _find_bot_owned_by(broken_uid)
        if bot:
            candidates.append(bot)

    for uid in candidates:
        try:
            auth.get_valid_access_token(uid)
            return uid
        except Exception:
            continue
    return None


def _recipient_email(broken_uid: str) -> str | None:
    """Always email the human owner, never the bot."""
    if _is_bot(broken_uid):
        owner = _owner_of_bot(broken_uid)
        if not owner:
            return None
        return _account_email(owner)
    return _account_email(broken_uid)


def _should_send(health: dict) -> str:
    """Returns 'first', 'reminder', or 'skip'."""
    if health.get("status") != "broken":
        return "skip"
    notes = health.get("notifications") or {}
    sent = notes.get("sent_count", 0)
    if sent == 0:
        return "first"
    if sent >= MAX_EMAILS:
        return "skip"
    first_at = notes.get("first_sent_at")
    if not first_at:
        return "skip"
    try:
        first_dt = datetime.fromisoformat(first_at)
    except Exception:
        return "skip"
    if datetime.now(timezone.utc) - first_dt >= timedelta(days=REMINDER_AFTER_DAYS):
        return "reminder"
    return "skip"


def _compose_email(broken_uid: str, classification: dict, is_reminder: bool) -> tuple[str, str]:
    label = _account_label(broken_uid)
    action = classification["action"]
    code = classification.get("code")
    reason = classification["message"]
    code_str = f"AADSTS{code}" if code else "(unknown)"

    if is_reminder:
        subject_prefix = "Reminder — "
    else:
        subject_prefix = ""

    if action == "re-login":
        subject = f"{subject_prefix}Action needed: {label.split(' (')[0]} needs to reconnect"
        reconnect_url = f"{APP_URL}{RECONNECT_PATH}"
        body_html = f"""
<p>Hi,</p>
<p>{label.capitalize()} stopped working because the Microsoft sign-in expired.</p>
<p><b>Reason:</b> {reason}<br/>
<b>Technical code:</b> {code_str}</p>
<p><b>How to fix (about 2 minutes):</b></p>
<ol>
  <li>Open <a href="{reconnect_url}">{reconnect_url}</a></li>
  <li>Go to the "AI Assistant" section in Settings</li>
  <li>Click <b>Reconnect</b> and sign in when prompted</li>
</ol>
<p style="color:#666;font-size:12px">Sent by Executive AI Platform. You will receive at most one reminder in 7 days if this isn't resolved.</p>
""".strip()
    else:  # contact-admin
        subject = f"{subject_prefix}IT admin help needed for {label.split(' (')[0]}"
        body_html = f"""
<p>Hi,</p>
<p>{label.capitalize()} can't sign in to Microsoft because of a tenant-level restriction.
You'll need your IT administrator to fix this — re-signing in won't work.</p>
<p><b>Reason:</b> {reason}<br/>
<b>Technical code:</b> {code_str}</p>
<p><b>What to forward to your IT admin:</b></p>
<blockquote style="border-left:3px solid #ccc;padding-left:12px;color:#444">
  Our Executive AI Platform reports error <b>{code_str}</b> on the account
  <b>{_account_email(broken_uid)}</b>. Microsoft says: "{reason}"
  Please investigate in the Microsoft Entra admin portal.
</blockquote>
<p>Once they fix it, your AI assistant will reconnect automatically — no further action needed from you.</p>
<p style="color:#666;font-size:12px">Sent by Executive AI Platform. You will receive at most one reminder in 7 days if this isn't resolved.</p>
""".strip()

    return subject, body_html


def check_and_notify(broken_uid: str):
    """Called after each auth failure. Decides whether to send an email
    based on the user's current health + notification history."""
    try:
        health = auth.get_auth_health(broken_uid)
        decision = _should_send(health)
        if decision == "skip":
            return

        recipient = _recipient_email(broken_uid)
        if not recipient:
            _log_dead_letter(broken_uid, "reason=no_recipient_email")
            return

        sender_uid = _pick_sender_uid(broken_uid)
        if not sender_uid:
            _log_dead_letter(broken_uid, "reason=no_working_sender_account")
            return

        last_err = health.get("last_error") or {}
        classification = classify_aadsts(last_err.get("code"), last_err.get("description") or "")

        is_reminder = decision == "reminder"
        subject, body = _compose_email(broken_uid, classification, is_reminder)

        token = auth.get_valid_access_token(sender_uid)
        GraphClient(token).send_mail(to=recipient, subject=subject, html=body)

        notes = health.get("notifications") or {}
        now_iso = datetime.now(timezone.utc).isoformat()
        if is_reminder:
            notes["reminder_sent_at"] = now_iso
            notes["sent_count"] = notes.get("sent_count", 1) + 1
        else:
            notes["first_sent_at"] = now_iso
            notes["sent_count"] = 1
        health["notifications"] = notes
        auth._save_health(broken_uid, health)

        print(f"[auth_notifier] Sent {'reminder' if is_reminder else 'initial'} alert "
              f"about {broken_uid} to {recipient} (via {sender_uid}, aadsts={classification.get('code')})")

    except Exception as e:
        _log_dead_letter(broken_uid, f"reason=exception  err={e!r}  tb={traceback.format_exc()[-300:]}")
