import json

IS_ACTION = False


def build(ctx):
    def read_settings(key: str = None) -> str:
        settings = ctx.settings
        user_model = ctx.user_model or {}
        combined = {**settings, "user_model": user_model}
        if key:
            if key in settings:
                return json.dumps({key: settings[key]}, ensure_ascii=False)
            if key in user_model:
                return json.dumps({key: user_model[key]}, ensure_ascii=False)
            return f"Key '{key}' not found in settings or user model."
        print(f"[Bot] read_settings()")
        return json.dumps(combined, ensure_ascii=False)
    return read_settings
