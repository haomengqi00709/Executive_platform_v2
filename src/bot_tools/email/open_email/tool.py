import json

IS_ACTION = False

_BODY_CAP = 4000   # keep the chat context bounded; full body is rarely needed beyond this


def build(ctx):
    def open_email(email_id: str) -> str:
        """Follow a stored pointer (email_id) back to the FULL original email."""
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        eid = (email_id or "").strip()
        if not eid:
            return ("Provide the email_id — the canonical id carried by a commitment, a reply_needed "
                    "item, a follow-up, or get_recent_emails.")
        try:
            m = owner_graph.get_message(eid)
        except Exception as e:
            return f"Couldn't open that email (the id may be stale or from another mailbox): {e}"
        if not m:
            return "No email found for that id."
        body = m.get("body") or {}
        content = body.get("content") or m.get("bodyPreview") or ""
        truncated = len(content) > _BODY_CAP
        out = {
            "email_id":  m.get("id", eid),
            "subject":   m.get("subject", ""),
            "from":      (m.get("from") or {}).get("emailAddress", {}).get("address", ""),
            "to":        [(r.get("emailAddress") or {}).get("address", "")
                          for r in (m.get("toRecipients") or [])],
            "received":  (m.get("receivedDateTime") or "")[:16],
            "body_type": body.get("contentType", "text"),
            "body":      content[:_BODY_CAP],
            "body_truncated": truncated,
        }
        print(f"[Bot] open_email({eid[:24]}…)")
        return json.dumps(out, ensure_ascii=False)
    return open_email
