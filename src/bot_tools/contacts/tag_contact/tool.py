IS_ACTION = True


def build(ctx):
    def tag_contact(name_or_email: str, tag: str, remove: bool = False) -> str:
        """Add or remove a tag/group label on ONE specific contact (resolved by name or email)."""
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        tag = (tag or "").strip()
        if not tag:
            return "Provide the tag/group label to apply."
        try:
            from src.modules.crm import load_crm, save_crm, find_contacts_by_name
            ref = (name_or_email or "").strip()
            contacts = load_crm(data_dir).get("contacts", {})
            # Resolve the reference → a single contact email.
            email = None
            if "@" in ref and ref.lower() in contacts:
                email = ref.lower()
            else:
                matches = find_contacts_by_name(data_dir, ref)
                if not matches:
                    return f"⚠️ I can't find a contact matching '{name_or_email}' — show the CRM and ask which."
                if len(matches) > 1:
                    who = "; ".join(f'[#{i+1}] {m.get("name")} <{m.get("email")}>'
                                    for i, m in enumerate(matches[:5]))
                    return (f"Several contacts match '{name_or_email}': {who}. "
                            f"Which one should I {'untag' if remove else 'tag'}?")
                email = matches[0]["email"].lower()

            crm = load_crm(data_dir)
            c = crm["contacts"].get(email)
            if not c:
                return f"⚠️ Contact {email} not found."
            tags = list(c.get("tags") or [])
            low = {t.lower() for t in tags}
            if remove:
                if tag.lower() not in low:
                    return f"'{c.get('name') or email}' isn't tagged '{tag}'."
                c["tags"] = [t for t in tags if t.lower() != tag.lower()]
                verb = "Removed tag"
            else:
                if tag.lower() in low:
                    return f"'{c.get('name') or email}' is already tagged '{tag}'."
                c["tags"] = tags + [tag]
                verb = "Tagged"
            save_crm(data_dir, crm)
            print(f"[Bot] tag_contact({email}, {tag!r}, remove={remove})")
            return f"✅ {verb}: \"{c.get('name') or email}\" {'' if remove else '→ '}{tag}".rstrip()
        except Exception as e:
            return f"Error tagging contact: {e}"
    return tag_contact
