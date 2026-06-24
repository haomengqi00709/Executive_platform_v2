import json
from collections import Counter
from datetime import datetime, timedelta, timezone

IS_ACTION = False


def build(ctx):
    def get_email_frequency_report(days_back: int = 30, top_n: int = 10) -> str:
        from src.bot import _with_indices, _register_list
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
            # Annotate each sender with its CRM identity so noise (newsletters / no-reply that are
            # NOT in the CRM) is distinguishable from real contacts.
            crm = {}
            try:
                from src.modules.crm import load_crm
                crm = load_crm(ctx.data_dir).get("contacts", {}) if ctx.data_dir else {}
            except Exception:
                pass
            rows = []
            for email, count in counts.most_common(top_n):
                c = crm.get(email.lower(), {})
                rows.append({
                    "email": email, "email_count": count, "in_crm": bool(c),
                    "name": c.get("name", ""), "status": c.get("status", ""),
                    "priority": c.get("priority", ""),
                })
            # Own bucket (was "contacts", which collided with find_contacts_by_name → "#N" resolved
            # against the wrong list). Distinct bucket = the registry shows them as separate lists.
            _register_list(ctx, "frequency_contacts", rows, "email",
                           label_fn=lambda it: f'{it.get("name") or it.get("email","")} '
                                               f'({it.get("email_count","")} emails'
                                               f'{"" if it.get("in_crm") else ", not in CRM"})',
                           source="most-emailed senders (raw volume)")
            result = _with_indices(rows)
            print(f"[Bot] get_email_frequency_report({days_back}d) → {len(result)} senders")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_email_frequency_report
