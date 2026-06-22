import json

IS_ACTION = False


def build(ctx):
    def list_group_members(group: str) -> str:
        from src.bot import _with_indices, _register_list
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        from src.modules.crm import resolve_group
        res = resolve_group(data_dir, group)
        if res["mode"] == "none":
            groups = res["all_groups"]
            if not groups:
                return f"You don't have any groups yet, so there's no group '{group}'."
            listing = ", ".join(f"{g['tag']} ({g['count']})" for g in groups[:20])
            return f"No group named '{group}'. Your groups are: {listing}."
        if res["mode"] == "substring" and len(res["candidate_tags"]) > 1:
            cands = ", ".join(f"{g['tag']} ({g['count']})" for g in res["candidate_tags"])
            return f"'{group}' matches several groups: {cands}. Which one?"
        tag = res["matched_tag"] or res["candidate_tags"][0]["tag"]
        members = [{"name": c.get("name") or c.get("email"), "email": c.get("email"),
                    "company": c.get("company", "")} for c in res["contacts"]]
        _register_list(ctx, "group_members", members, "email",
                       label_fn=lambda it: f'{it.get("name","")} <{it.get("email","")}>',
                       source=f"members of {tag}")
        return json.dumps({"group": tag, "count": len(members),
                           "members": _with_indices(members)}, ensure_ascii=False)
    return list_group_members
