IS_ACTION = False


def build(ctx):
    def update_setting(key: str, value: str) -> str:
        import json as _j
        from src.bot import _save_user_model
        try:
            parsed = _j.loads(value)
        except Exception:
            parsed = value
        if ctx.user_model is None:
            ctx.user_model = {}
        ctx.user_model[key] = parsed          # in-place so reply()/read_settings see it
        _save_user_model(ctx.user_model_path, ctx.user_model)
        print(f"[Bot] update_setting({key}={parsed!r})")
        return f"✅ Preference updated: {key}"
    return update_setting
