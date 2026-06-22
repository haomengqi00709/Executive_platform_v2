import json
from datetime import datetime, timedelta, timezone

IS_ACTION = False


def build(ctx):
    def get_recent_emails(hours_back: int = 48, top: int = 15) -> str:
        from src.bot import _with_indices, _register_list
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            msgs   = owner_graph.get_messages(top=top)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            result = []
            for m in msgs:
                recv = m.get("receivedDateTime", "")
                try:
                    dt = datetime.fromisoformat(recv.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
                result.append({
                    "email_id":   m.get("id", ""),
                    "subject":    m.get("subject", ""),
                    "from":       m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "received":   recv[:16],
                    "preview":    (m.get("bodyPreview") or "")[:200],
                    "is_read":    m.get("isRead", True),
                    "importance": m.get("importance", "normal"),
                })
            result = _with_indices(result)
            _register_list(ctx, "emails", result, "email_id",
                           label_fn=lambda it: f'{it.get("from","")} — "{(it.get("subject") or "")[:50]}"',
                           source="recent emails")
            print(f"[Bot] get_recent_emails({hours_back}h) → {len(result)}")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_recent_emails
