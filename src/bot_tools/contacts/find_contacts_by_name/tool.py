import json

IS_ACTION = False


def build(ctx):
    def find_contacts_by_name(name: str) -> str:
        from src.bot import _with_indices
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import find_contacts_by_name as _crm_find
            matches = _crm_find(data_dir, name)
            print(f"[Bot] find_contacts_by_name({name!r}) → {len(matches)}")
            if not matches:
                return f"No CRM contact matching '{name}'. Ask the user for the email address."
            return json.dumps(_with_indices(matches), ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return find_contacts_by_name
