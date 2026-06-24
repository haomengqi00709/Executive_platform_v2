import json

IS_ACTION = False

_PRANK = {"high": 0, "medium": 1, "low": 2, "": 3, "ignore": 4}


def build(ctx):
    def list_crm_contacts(status: str = "", priority: str = "", tag: str = "", limit: int = 25) -> str:
        """List CRM contacts filtered by status / priority / tag (the curated CRM, not inbox volume)."""
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.bot import _with_indices, _register_list
            from src.modules.crm import load_crm
            contacts = load_crm(data_dir).get("contacts", {})
            st, pr, tg = status.strip().lower(), priority.strip().lower(), tag.strip().lower()
            rows = []
            for email, c in contacts.items():
                if c.get("archived"):
                    continue
                if st and (c.get("status") or "").lower() != st:
                    continue
                if pr and (c.get("priority") or "").lower() != pr:
                    continue
                if tg and not any(tg in (t or "").lower() for t in (c.get("tags") or [])):
                    continue
                rows.append({
                    "email": email, "name": c.get("name", ""), "company": c.get("company", ""),
                    "role": c.get("role", ""), "status": c.get("status", ""),
                    "priority": c.get("priority", ""), "tags": c.get("tags") or [],
                    "last_contact": c.get("last_contact", ""),
                })
            rows.sort(key=lambda r: (r.get("last_contact") or ""), reverse=True)
            rows.sort(key=lambda r: _PRANK.get((r.get("priority") or "").lower(), 3))
            total = len(rows)
            rows = _with_indices(rows[:max(1, limit)])
            _register_list(
                ctx, "crm_contacts", rows, "email",
                label_fn=lambda it: f'{it.get("name") or it.get("email","")} '
                                    f'[{it.get("status","")}/{it.get("priority") or "—"}]',
                source="crm contacts")
            crit = ", ".join(f"{k}={v}" for k, v in
                             (("status", st), ("priority", pr), ("tag", tg)) if v) or "all"
            print(f"[Bot] list_crm_contacts({crit}) → {len(rows)}/{total}")
            return json.dumps({"criteria": crit, "shown": len(rows), "total": total,
                               "contacts": rows}, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return list_crm_contacts
