import json

IS_ACTION = False


def build(ctx):
    def list_my_groups() -> str:
        from src.bot import _with_indices
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        from src.modules.crm import list_groups
        groups = list_groups(data_dir)
        if not groups:
            return ("You don't have any contact groups yet. Tag contacts in the CRM "
                    "(or use 'Save as group' after selecting people) to create one.")
        return json.dumps({"groups": _with_indices(groups)}, ensure_ascii=False)
    return list_my_groups
