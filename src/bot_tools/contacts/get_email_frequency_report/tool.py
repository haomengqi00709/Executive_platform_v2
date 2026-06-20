import json
from collections import Counter
from datetime import datetime, timedelta, timezone

IS_ACTION = False


def build(ctx):
    def get_email_frequency_report(days_back: int = 30, top_n: int = 10) -> str:
        from src.bot import _with_indices
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            msgs   = owner_graph.get_messages(top=200)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
            counts: Counter = Counter()
            for m in msgs:
                recv = m.get("receivedDateTime", "")
                try:
                    dt = datetime.fromisoformat(recv.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
                sender = m.get("from", {}).get("emailAddress", {}).get("address", "")
                if sender:
                    counts[sender] += 1
            result = _with_indices([
                {"email": email, "email_count": count}
                for email, count in counts.most_common(top_n)
            ])
            print(f"[Bot] get_email_frequency_report({days_back}d) → {len(result)} contacts")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_email_frequency_report
