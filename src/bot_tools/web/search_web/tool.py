"""search_web — web search via Gemini google_search grounding.
Migrated from bot.py; standalone (needs no per-request context)."""
from google.genai import types

IS_ACTION = False


def build(ctx):
    def search_web(query: str) -> str:
        import src.bot as _bot
        try:
            resp = _bot._client().models.generate_content(
                model=_bot.MODEL,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            _bot._record_bot_usage(resp, "bot_search", is_search=True)
            result = resp.text or "No results found."
            print(f"[Bot] search_web → {len(result)} chars")
            return result
        except Exception as e:
            return f"Search error: {e}"
    return search_web
