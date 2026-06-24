import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

IS_ACTION = False


def _owner_addresses(data_dir, settings: dict) -> set:
    """The owner's own addresses, to exclude self from the activity count."""
    addrs = set()
    rep = (settings or {}).get("report_email")
    if rep:
        addrs.add(rep.lower())
    try:
        uid = Path(data_dir).name
        sess = Path(data_dir).parent / "_sessions" / f"{uid}.json"
        if sess.exists():
            u = json.loads(sess.read_text()).get("username")
            if u:
                addrs.add(u.lower())
    except Exception:
        pass
    return addrs


def build(ctx):
    def get_email_frequency_report(days_back: int = 30, top_n: int = 10) -> str:
        from src.bot import _with_indices, _register_list
        from src.modules.crm import _is_noise
        owner_graph = ctx.owner_graph
        if owner_graph is None:
            return "Owner account not available."
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
            own = _owner_addresses(ctx.data_dir, ctx.settings)

            def _fresh(ts):
                try:
                    return datetime.fromisoformat((ts or "").replace("Z", "+00:00")) >= cutoff
                except Exception:
                    return True

            inbound, outbound = Counter(), Counter()
            # Inbound: who emails the owner (received).
            for m in owner_graph.get_messages(top=200):
                if not _fresh(m.get("receivedDateTime")):
                    continue
                a = (m.get("from", {}).get("emailAddress", {}).get("address", "") or "").lower()
                if a and a not in own and not _is_noise(a):
                    inbound[a] += 1
            # Outbound: who the owner emails (sent).
            try:
                for m in owner_graph.get_sent_messages_since(days=days_back, max_results=300):
                    for r in (m.get("toRecipients") or []):
                        a = ((r.get("emailAddress") or {}).get("address", "") or "").lower()
                        if a and a not in own and not _is_noise(a):
                            outbound[a] += 1
            except Exception as e:
                print(f"[Bot] frequency: sent-mail fetch skipped: {e}")

            # Two-way activity = inbound + outbound, automated/no-reply senders dropped.
            total = Counter()
            for a, n in inbound.items():
                total[a] += n
            for a, n in outbound.items():
                total[a] += n

            crm = {}
            try:
                from src.modules.crm import load_crm
                crm = load_crm(ctx.data_dir).get("contacts", {}) if ctx.data_dir else {}
            except Exception:
                pass

            rows = []
            for email, cnt in total.most_common(top_n):
                c = crm.get(email, {})
                rows.append({
                    "email": email, "activity": cnt,
                    "received": inbound.get(email, 0), "sent": outbound.get(email, 0),
                    "in_crm": bool(c), "name": c.get("name", ""),
                    "status": c.get("status", ""), "priority": c.get("priority", ""),
                })
            _register_list(ctx, "frequency_contacts", rows, "email",
                           label_fn=lambda it: f'{it.get("name") or it.get("email","")} '
                                               f'({it.get("activity","")} msgs: '
                                               f'{it.get("received",0)} in / {it.get("sent",0)} out)',
                           source="most active contacts (two-way, automated senders excluded)")
            result = _with_indices(rows)
            print(f"[Bot] get_email_frequency_report({days_back}d, two-way) → {len(result)} contacts")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_email_frequency_report
