"""
Alert sender: Teams Adaptive Card (primary) + SMTP email (backup).

Called by poller.run() with the list of transitions diff() returned. Dedup
is delegated to state.was_recently_alerted() so the same incident doesn't
spam every 60s — re-alert only after ALERT_REPEAT_HOURS (default 6h).
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

from . import state

log = logging.getLogger("ops.alerter")

ALERT_REPEAT_HOURS = int(os.getenv("ALERT_REPEAT_HOURS", "6"))


def alert(transitions: list[dict]) -> None:
    for t in transitions:
        # Recoveries always send; breaks dedup by 6h
        is_recovery = t["type"].endswith("_recovered")
        if not is_recovery and state.was_recently_alerted(t, hours=ALERT_REPEAT_HOURS):
            log.info("dedup skip: %s (alerted in last %dh)", t["key"], ALERT_REPEAT_HOURS)
            continue
        teams_ok = _send_teams(t)
        email_ok = _send_email(t)
        state.record_alert(t)
        log.info("alerted %s — teams=%s email=%s", t["key"], teams_ok, email_ok)


def _summary(t: dict) -> tuple[str, str, str]:
    """Returns (title, body, color) for a transition."""
    who = t.get("username") or t.get("uid", "")[:8]
    typ = t["type"]
    if typ == "auth_broken":
        title = f"Auth broken: {who}"
        body  = f"User '{who}' is failing token refresh."
        if t.get("since"):
            body += f" Broken since {t['since']}."
        if t.get("error"):
            body += f"\nLast error: {t['error']}"
        color = "attention"
    elif typ == "auth_recovered":
        title = f"Auth recovered: {who}"
        body  = f"User '{who}' is healthy again."
        color = "good"
    else:
        title = f"Event: {typ}"
        body  = f"{who}: {typ}"
        color = "default"
    return title, body, color


def _send_teams(t: dict) -> bool:
    url = os.getenv("TEAMS_WEBHOOK_URL")
    if not url:
        log.debug("no TEAMS_WEBHOOK_URL — skipping Teams")
        return False

    title, body, color = _summary(t)

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type":    "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder",
             "size": "Medium", "color": color, "wrap": True},
            {"type": "TextBlock", "text": body, "wrap": True,
             "spacing": "Small"},
            {"type": "TextBlock", "text": f"uid: {t.get('uid','')}",
             "isSubtle": True, "size": "Small", "spacing": "Small"},
        ],
    }
    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content":     card,
        }],
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 400:
            log.warning("Teams webhook %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("Teams send failed: %s", e)
        return False


def _send_email(t: dict) -> bool:
    host = os.getenv("SMTP_HOST")
    if not host:
        log.debug("no SMTP_HOST — skipping email")
        return False

    port      = int(os.getenv("SMTP_PORT", "587"))
    user      = os.getenv("SMTP_USER")
    password  = os.getenv("SMTP_PASS")
    from_addr = os.getenv("SMTP_FROM") or user or ""
    to_addr   = os.getenv("SMTP_TO")

    if not (user and password and from_addr and to_addr):
        log.debug("SMTP not fully configured — skipping email")
        return False

    title, body, _ = _summary(t)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[CEO Ops] {title}"
    msg["From"]    = from_addr
    msg["To"]      = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:
        log.warning("SMTP send failed: %s", e)
        return False
