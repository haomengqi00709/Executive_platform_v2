"""The OpenAI-compatible fallback adapter (src/bot_fallback.py) translates our canonical genai
`contents`/tools into OpenAI shape and back. These guard each translator in isolation (no
network): gating, once-generated tool schemas (with type lowercasing), contents→messages with
tool_call/tool_result id pairing, and OpenAI-response→genai-Part."""
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_fb_test_"))
os.environ.setdefault("GEMINI_API_KEY", "dummy-offline-key")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402
from src import bot_fallback as fb  # noqa: E402


def test_is_enabled_requires_key_and_model(monkeypatch):
    monkeypatch.delenv("FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    assert fb.is_enabled() is False
    monkeypatch.setenv("FALLBACK_API_KEY", "sk-x")
    assert fb.is_enabled() is False            # key without model → still off
    monkeypatch.setenv("FALLBACK_MODEL", "deepseek-chat")
    assert fb.is_enabled() is True


def test_normalize_schema_lowercases_gemini_types():
    src = {"type": "OBJECT", "properties": {"n": {"type": "STRING"}, "k": {"type": "INTEGER"}},
           "required": ["n"]}
    out = fb._normalize_schema(src)
    assert out["type"] == "object"
    assert out["properties"]["n"]["type"] == "string"
    assert out["properties"]["k"]["type"] == "integer"
    assert out["required"] == ["n"]            # non-type values untouched


def test_tool_schemas_cover_all_tools_openai_shape():
    import tempfile as _t
    os.environ.setdefault("DATA_DIR", _t.mkdtemp())
    from src.bot_tools import registry

    class Ctx:
        owner_graph = graph = None; state = {}; data_dir = None
        settings = {}; wiki_dir = None; user_model = {}; user_model_path = None
    tools, _, _ = registry.build(Ctx())
    fb._schema_cache = None                     # reset the process cache for a clean run
    schemas = fb._tool_schemas(tools)
    assert len(schemas) == len(tools) and len(tools) >= 30
    for s in schemas:
        assert s["type"] == "function"
        assert s["function"]["name"] and isinstance(s["function"]["parameters"], dict)
    # no leftover UPPERCASE gemini types anywhere
    import json
    assert '"STRING"' not in json.dumps(schemas) and '"OBJECT"' not in json.dumps(schemas)


def test_contents_to_messages_pairs_tool_calls_with_results():
    contents = [
        types.Content(role="user",  parts=[types.Part(text="find apollo")]),
        types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="search", args={"what": "emails", "query": "apollo"}))]),
        types.Content(role="user",  parts=[types.Part(
            function_response=types.FunctionResponse(name="search", response={"result": "[]"}))]),
    ]
    msgs = fb._contents_to_messages(contents, "SYSTEM PROMPT")
    assert msgs[0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert msgs[1] == {"role": "user", "content": "find apollo"}
    assert msgs[2]["role"] == "assistant" and msgs[2]["tool_calls"][0]["function"]["name"] == "search"
    assert msgs[3]["role"] == "tool" and msgs[3]["content"] == "[]"
    # the tool result is bound to the assistant's tool_call by id
    assert msgs[2]["tool_calls"][0]["id"] == msgs[3]["tool_call_id"]
    import json
    assert json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"]) == {"what": "emails", "query": "apollo"}


def test_response_to_parts_tool_call():
    tc = SimpleNamespace(function=SimpleNamespace(name="get_recent_emails", arguments='{"hours_back": 24}'))
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))])
    parts, fr, pf = fb._response_to_parts(resp)
    assert fr == "tool_calls" and len(parts) == 1
    assert parts[0].function_call.name == "get_recent_emails"
    assert dict(parts[0].function_call.args) == {"hours_back": 24}


def test_response_to_parts_text():
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Hello Daniel.", tool_calls=None))])
    parts, fr, pf = fb._response_to_parts(resp)
    assert fr == "stop" and parts[0].text == "Hello Daniel." and parts[0].function_call is None


def test_response_to_parts_empty():
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=None))])
    parts, fr, _ = fb._response_to_parts(resp)
    assert parts == [] and fr == "empty"
