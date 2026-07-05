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
        # "#N" / bare position → resolve through the list the user actually saw (deterministic,
        # same pattern as commitments resolve_ref). Transcribing a 150-char Graph id is exactly
        # the kind of long canonical value the model corrupts (live failure: 'open 1' → model
        # copy-typed the id with repeated substrings → Graph 400). Positions can't be corrupted.
        ref = eid.lstrip("#").strip()
        if ref.isdigit():
            try:
                buckets = (getattr(ctx, "state", None) or {}).get("_shown_lists") or {}
            except Exception:
                buckets = {}
            em = buckets.get("emails") or {}
            shown = em.get("items") or []
            newest_ts = max((b.get("ts") or 0) for b in buckets.values()) if buckets else 0
            # Only positional-resolve when the EMAIL list is the freshest thing the user saw —
            # "open 1" right after a commitments list must not open stale email #1.
            if shown and (em.get("ts") or 0) >= newest_ts:
                hit = next((it for it in shown if it.get("pos") == int(ref) and it.get("id")), None)
                if hit:
                    eid = hit["id"]
                else:
                    return (f"No email at position {ref} in the last shown email list "
                            f"(it has {len(shown)} items). Ask the user which one they mean.")
            elif not shown:
                return ("No email list is currently shown — run search/get_recent_emails first, "
                        "then open by its [#N] position.")
            # else: a fresher non-email list is on screen — fall through so a commitment id /
            # full email_id still works; a bare digit will fail Graph and return the honest error.
        # The model often passes a COMMITMENT's id (a short hash) instead of its email_id (a long
        # Graph id). If the value matches a commitment row, follow that pointer to the real email_id.
        try:
            from src.modules import commitments_store
            for c in commitments_store.query_visible(ctx.data_dir):
                if c.get("id") == eid and c.get("email_id"):
                    eid = c["email_id"]
                    break
        except Exception:
            pass
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
