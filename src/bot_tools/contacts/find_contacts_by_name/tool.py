import json

IS_ACTION = False


def build(ctx):
    def find_contacts_by_name(name: str) -> str:
        from src.bot import _with_indices, _register_list
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        try:
            from src.modules.crm import find_contacts_by_name as _crm_find
            matches = _crm_find(data_dir, name)
            print(f"[Bot] find_contacts_by_name({name!r}) → {len(matches)}")
            if not matches:
                return f"No CRM contact matching '{name}'. Ask the user for the email address."
            _register_list(ctx, "contacts", matches, "email",
                           label_fn=lambda it: f'{it.get("name","")} — {it.get("company","")} <{it.get("email","")}>',
                           source=f"contacts named {name}")
            return json.dumps(_with_indices(matches), ensure_ascii=False)
        except Exception as e:
            return f"Error: {e}"
    return find_contacts_by_name
