import json

IS_ACTION = False


def build(ctx):
    def list_my_groups() -> str:
        from src.bot import _with_indices, _register_list
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        from src.modules.crm import list_groups
        groups = list_groups(data_dir)
        if not groups:
            return ("You don't have any contact groups yet. Tag contacts in the CRM "
                    "(or use 'Save as group' after selecting people) to create one.")
        _register_list(ctx, "groups", groups, "tag",
                       label_fn=lambda it: f'{it.get("tag","")} ({it.get("count","")})',
                       source="your groups")
        return json.dumps({"groups": _with_indices(groups)}, ensure_ascii=False)
    return list_my_groups
