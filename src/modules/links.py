"""URL helpers shared across Teams-send code paths.

The redirector itself is `GET /r/draft` in server.py — this module just
constructs the public URL that points at it, so we have one place to read
APP_URL and one place to format the link.
"""
import os
from urllib.parse import quote, urlparse


def _app_base_url() -> str:
    """Public base URL for redirector links. Same pattern as auth_notifier.APP_URL:
    explicit APP_URL wins, otherwise strip /auth/* off REDIRECT_URI, finally
    fall back to localhost for dev."""
    url = (
        os.getenv("APP_URL")
        or os.getenv("REDIRECT_URI", "").rsplit("/auth/", 1)[0]
        or "http://localhost:8000"
    )
    return url.rstrip("/")


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
    return f"{_app_base_url()}/r/draft?url={quote(web_link, safe='')}"
