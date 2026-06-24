IS_ACTION = True

# Mirror server.py:3394 _PROJECT_EDITABLE_FIELDS / _PROJECT_VALID_STATUSES / _PROJECT_VALID_MOMENTUMS
# (kept local to avoid importing src.server at tool-load time).
_EDITABLE = {"status", "momentum", "category", "summary", "next_action", "name", "deadline", "ignore"}
_VALID_STATUS = {"ongoing", "needs_attention", "paused", "early_stage", "completed"}
_VALID_MOMENTUM = {"accelerating", "steady", "slowing", "stalled"}


def build(ctx):
    def modify_project(index_or_hint: str, field: str, value: str) -> str:
        from src.modules import projects_store
        from src.bot_tools.projects._shared import resolve_project_ref
        from src.modules.tz import today_local_str
        data_dir = ctx.data_dir
        if not data_dir:
            return "No data directory available."
        field = (field or "").strip().lower()
        if field not in _EDITABLE:
            return f"⚠️ Can't set '{field}'. Editable fields: {', '.join(sorted(_EDITABLE))}."

        pid, name = resolve_project_ref(ctx, data_dir, index_or_hint)
        if not pid:
            return (f"⚠️ I can't match '{index_or_hint}' to a project on your current list — "
                    f"show the projects and ask which; don't claim it's changed.")

        # Coerce / validate (field-level update never touches sibling user columns).
        if field == "ignore":
            val = str(value).strip().lower() in ("true", "1", "yes", "y", "ignore")
        else:
            val = str(value).strip()
            if field == "status" and val not in _VALID_STATUS:
                return f"⚠️ Invalid status '{val}'. One of: {', '.join(sorted(_VALID_STATUS))}."
            if field == "momentum" and val not in _VALID_MOMENTUM:
                return f"⚠️ Invalid momentum '{val}'. One of: {', '.join(sorted(_VALID_MOMENTUM))}."

        updated = projects_store.update_project_fields(
            data_dir, pid, {field: val}, today_local_str(data_dir))
        if updated is None:
            return f"⚠️ Project '{name or pid}' not found in the store."
        print(f"[Bot] modify_project({pid}, {field}={val!r})")
        return f"✅ Set {field} = {val} on \"{name or pid}\"."
    return modify_project
