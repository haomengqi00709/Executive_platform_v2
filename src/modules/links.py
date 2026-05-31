"""URL helpers shared across Teams-send code paths.

The redirector itself is `GET /r/draft` in server.py — this module just
constructs the public URL that points at it, so we have one place to read
APP_URL and one place to format the link.
"""
import os
from urllib.parse import quote, urlparse


def _app_base_url() -> str:
    """Public base URL for redirector links.

    Resolution order: APP_URL → REDIRECT_URI (with /auth/* stripped).
    Returns "" when neither yields a deployed URL (i.e. localhost or unset).
    Callers must handle the empty case by not wrapping the URL with a redirect,
    so users in Teams always get a clickable link instead of a dead localhost."""
    url = os.getenv("APP_URL") or os.getenv("REDIRECT_URI", "").rsplit("/auth/", 1)[0]
    if not url:
        return ""
    url = url.rstrip("/")
    # localhost links would be dead for any Teams user — treat as "no base URL"
    if url.startswith("http://localhost") or url.startswith("http://127."):
        return ""
    return url


_OUTLOOK_HOSTS = (
    "outlook.office.com",
    "outlook.office365.com",
    "outlook.live.com",
)


def wrap_draft_link(web_link: str) -> str:
    """Wrap a Microsoft Graph webLink with our `/r/draft` redirector so
    Teams clicks try the Outlook app first on mobile, fall back to web.

    If `web_link` is empty or not an Outlook URL we pass it through
    unchanged — better to keep a slightly-less-ideal link than to drop
    the user's only way of reaching the draft."""
    if not web_link:
        return ""
    try:
        host = (urlparse(web_link).hostname or "").lower()
    except Exception:
        return web_link
    if not any(host == h or host.endswith("." + h) for h in _OUTLOOK_HOSTS):
        return web_link
    base = _app_base_url()
    if not base:
        # No deployed base URL — pass the Outlook web_link through unchanged
        # rather than emit a dead-end localhost or example.com link.
        return web_link
    return f"{base}/r/draft?url={quote(web_link, safe='')}"
