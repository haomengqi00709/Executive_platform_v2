import json

IS_ACTION = False


def build(ctx):
    def check_email_handling(query: str) -> str:
        from src.bot import _with_indices
        from src.modules.subject_match import normalize_subject
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        q = (query or "").strip()
        if not q:
            return "Please provide a query (sender name, subject keyword, etc.)."
        q_low = q.lower()
        q_norm = normalize_subject(q)

        def _scan(section_id: str, who_key: str) -> list:
            path = data_dir / "results" / f"{section_id}.json"
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text())
            except Exception:
                return []
            out = []
            who_name_key = "from_name" if who_key == "from_email" else "to_name"
            for it in (data.get("items") or []):
                subj = it.get("subject") or ""
                who_email = (it.get(who_key) or "")
                who_name = (it.get(who_name_key) or "")
                hay = f"{subj} {who_name} {who_email}".lower()
                hay_norm = normalize_subject(subj)
                if q_low in hay or (q_norm and q_norm in hay_norm):
                    out.append({
                        "section":  section_id,
                        "email_id": it.get("email_id"),
                        "subject":  subj,
                        "who":      who_email,
                        "status":   "open",
                    })
            for h in (data.get("handled") or []):
                hay = f"{h.get('email_subject','')} {h.get('email_from','')} {h.get('email_to','')}".lower()
                hay_norm = normalize_subject(h.get("email_subject", ""))
                if q_low in hay or (q_norm and q_norm in hay_norm):
                    out.append({
                        "section":    section_id,
                        "email_id":   h.get("email_id"),
                        "subject":    h.get("email_subject"),
                        "who":        h.get("email_from") or h.get("email_to"),
                        "status":     "handled",
                        "handled_by": h.get("handled_by"),
                    })
            return out

        matches = _scan("reply_needed", "from_email") + _scan("followup_needed", "to_email")

        seen = set()
        unique = []
        for m in matches:
            key = (m["section"], m["email_id"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)

        print(f"[Bot] check_email_handling({query!r}) → {len(unique)} matches")
        if not unique:
            return json.dumps({
                "matches": [],
                "note": f"No recent email matches '{query}' in reply_needed or followup_needed. "
                        f"The system only tracks emails from the last 14 days.",
            }, ensure_ascii=False)
        return json.dumps({"matches": _with_indices(unique[:8])}, ensure_ascii=False)
    return check_email_handling
