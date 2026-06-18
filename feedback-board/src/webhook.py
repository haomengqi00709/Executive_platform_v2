"""GitHub push webhook → auto-close requests.

When you push with a commit message mentioning `REQ-7`, GitHub POSTs the push here
and the matching request flips to done. Server-to-server: the team never touches
GitHub; only the developer pushes.

Pure functions (verify_signature, extract_closures) are separated from the FastAPI
endpoint so they're unit-testable without a running server.
"""
import hashlib
import hmac
import re

from . import state

_REQ_RE = re.compile(r"\bREQ-(\d+)\b", re.IGNORECASE)


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Validate GitHub's X-Hub-Signature-256 (HMAC-SHA256 of the raw body)."""
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def extract_closures(payload: dict) -> list[dict]:
    """From a GitHub push payload, return one {req_id, sha, url} per (request,
    commit) mention. A commit can close several requests; dedup per request keeps
    the FIRST commit that mentioned it."""
    seen: set[str] = set()
    closures: list[dict] = []
    for c in payload.get("commits", []) or []:
        msg = c.get("message", "") or ""
        sha = (c.get("id") or "")[:10]
        url = c.get("url")
        for m in _REQ_RE.finditer(msg):
            req_id = f"REQ-{int(m.group(1))}"
            if req_id in seen:
                continue
            seen.add(req_id)
            closures.append({"req_id": req_id, "sha": sha, "url": url})
    return closures


def apply_closures(closures: list[dict]) -> dict:
    """Mark each referenced request done (idempotent). Returns which ids were
    closed vs not found."""
    closed, not_found = [], []
    for c in closures:
        req = state.mark_done_by_ref(c["req_id"], c["sha"], c.get("url"))
        (closed if req else not_found).append(c["req_id"])
    return {"closed": closed, "not_found": not_found}
