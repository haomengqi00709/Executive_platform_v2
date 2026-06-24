import json

IS_ACTION = False


def build(ctx):
    def get_contact_history(email: str) -> str:
        from src.bot import _with_indices
        wiki_dir = ctx.wiki_dir
        data_dir = ctx.data_dir
        try:
            result = {"email": email, "emails": [], "meetings": []}
            if wiki_dir and wiki_dir.exists():
                index_path = wiki_dir / "_index.json"
                if index_path.exists():
                    index = json.loads(index_path.read_text())
                    for proj_id, proj in index.items():
                        participants = proj.get("participants") or []
                        if any(
                            email.lower() in (p.lower() if isinstance(p, str) else "")
                            for p in participants
                        ):
                            proj_path = wiki_dir / f"{proj_id}.json"
                            if proj_path.exists():
                                proj_data = json.loads(proj_path.read_text())
                                result["meetings"].extend(proj_data.get("meetings", [])[:5])
                                result["emails"].extend(proj_data.get("emails", [])[:5])
            if data_dir:
                try:
                    from src.modules.crm import load_crm
                    crm = load_crm(data_dir)
                    contact = crm.get("contacts", {}).get(email.lower(), {})
                    if contact:
                        # The CRM profile (was: only writing_style) — so the bot can answer
                        # "who is X / what's their status / priority / my notes" from the curated CRM.
                        result["crm"] = {
                            "name":         contact.get("name", ""),
                            "company":      contact.get("company", ""),
                            "role":         contact.get("role", ""),
                            "status":       contact.get("status", ""),
                            "priority":     contact.get("priority", ""),
                            "tags":         contact.get("tags") or [],
                            "notes":        contact.get("notes", ""),
                            "last_contact": contact.get("last_contact", ""),
                            "thread_count": contact.get("thread_count", 0),
                        }
                        ws = (contact.get("writing_style") or "").strip()
                        if ws:
                            result["writing_style_note"] = ws
                except Exception:
                    pass
            result["emails"]   = _with_indices(result["emails"])
            result["meetings"] = _with_indices(result["meetings"])
            print(f"[Bot] get_contact_history({email})")
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return get_contact_history
