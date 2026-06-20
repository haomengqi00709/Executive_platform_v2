IS_ACTION = True


def build(ctx):
    def tag_recent_contacts(tag: str, hours: int = 24) -> str:
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import tag_contacts_added_since
            n = tag_contacts_added_since(data_dir, tag, hours)
            if n == 0:
                return f"No contacts found added in the last {hours}h."
            return f"✅ Tagged {n} contact{'s' if n != 1 else ''} with '{tag}'."
        except Exception as e:
            return f"Error tagging contacts: {e}"
    return tag_recent_contacts
