"""OpenAI-compatible model fallback for the Teams bot (Hermes rung 4).

When the primary Gemini call keeps returning empty (or errors), the bot switches to a
fallback model that speaks the OpenAI Chat Completions API — DeepSeek / Qwen / OpenAI /
anything OpenAI-compatible, chosen entirely by env config:

    FALLBACK_API_KEY   — enables the fallback when set (with FALLBACK_MODEL)
    FALLBACK_MODEL     — e.g. "deepseek-chat", "qwen-max", "gpt-4o-mini"
    FALLBACK_BASE_URL  — provider endpoint (default: OpenAI)

The primary genai path is untouched. This module only runs on the fallback boundary:
it translates our canonical genai `contents`/tools into OpenAI shape, calls the provider,
and translates the reply BACK into real genai `types.Part` objects so the rest of the bot
loop (tool dispatch, contents accumulation) consumes it identically to a Gemini response.
Default OFF — with no env set, is_enabled() is False and the bot behaves exactly as before.
"""
import json
import os
import threading
from types import SimpleNamespace

from google import genai
from google.genai import types

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

_client_lock = threading.Lock()
_oai_clients: dict = {}          # base_url → OpenAI client (one httpx transport per endpoint)
_schema_cache: list | None = None
_genai_schema_client = None


# ── provider rows ────────────────────────────────────────────────────────────
# A provider row is a dict {base_url, model, key_env[, key_env_fallback]} — the same shape as
# ai.PROVIDERS entries. provider=None everywhere means the legacy FALLBACK_* env trio, kept
# for backward compatibility (tests, /fallback health checks, non-registry deployments).

def _legacy_row() -> dict:
    return {"base_url": os.getenv("FALLBACK_BASE_URL", "").strip() or _DEFAULT_BASE_URL,
            "model": os.getenv("FALLBACK_MODEL", "").strip(),
            "_key": os.getenv("FALLBACK_API_KEY", "").strip()}


def _row(provider: dict | None) -> dict:
    return dict(provider) if provider else _legacy_row()


def _row_key(row: dict) -> str:
    if row.get("_key"):
        return row["_key"]
    return (os.getenv(row.get("key_env") or "", "")
            or os.getenv(row.get("key_env_fallback") or "", "")).strip()


def model_name(provider: dict | None = None) -> str:
    return _row(provider).get("model", "")


def available(provider: dict | None = None) -> bool:
    """True when this engine config has both a key and a model resolvable."""
    row = _row(provider)
    return bool(_row_key(row) and row.get("model"))


def default_alt_row() -> dict | None:
    """The OpenAI-compatible engine to use as the ALTERNATE when the primary is Gemini:
    the registry's kimi row if its key resolves, else the legacy FALLBACK_* env config."""
    try:
        from src.ai import PROVIDERS
        kimi = PROVIDERS.get("kimi")
        if kimi and available(kimi):
            return kimi
    except Exception:
        pass
    return _legacy_row() if available(None) else None


def _model() -> str:
    # legacy accessor (back-compat for callers/tests that predate provider rows)
    return _legacy_row()["model"]


def is_enabled() -> bool:
    """Legacy gate: the FALLBACK_* env trio is configured (back-compat)."""
    return available(None)


def _client(provider: dict | None = None):
    row = _row(provider)
    base = (row.get("base_url") or _DEFAULT_BASE_URL).strip()
    cli = _oai_clients.get(base)
    if cli is None:
        with _client_lock:
            cli = _oai_clients.get(base)
            if cli is None:
                from openai import OpenAI
                cli = OpenAI(api_key=_row_key(row), base_url=base)
                _oai_clients[base] = cli
    return cli


# ── tool schemas: generated ONCE from the raw callables, reused every call ────
def _normalize_schema(node):
    """genai emits JSON-Schema with UPPERCASE types (STRING/OBJECT/…); OpenAI/JSON-Schema
    wants lowercase. Recursively lowercase every `type` value; leave everything else."""
    if isinstance(node, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _normalize_schema(v))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_normalize_schema(x) for x in node]
    return node


def _tool_schemas(all_tools) -> list:
    """OpenAI `tools` array built once from our Python callables — reuses genai's own
    callable→schema extraction (verified 40/40), then normalizes types + wraps in the
    OpenAI function envelope. Cached for the process (tool set is static)."""
    global _schema_cache, _genai_schema_client
    if _schema_cache is not None:
        return _schema_cache
    if _genai_schema_client is None:
        _genai_schema_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", "x"))
    out = []
    for fn in all_tools:
        try:
            fd = types.FunctionDeclaration.from_callable(client=_genai_schema_client, callable=fn).to_json_dict()
            out.append({"type": "function", "function": {
                "name": fd.get("name") or fn.__name__,
                "description": fd.get("description", "") or "",
                "parameters": _normalize_schema(fd.get("parameters") or {"type": "object", "properties": {}}),
            }})
        except Exception as e:
            print(f"[BotFallback] schema-gen skipped {getattr(fn, '__name__', '?')}: {e}")
    _schema_cache = out
    return out


# ── translation: genai contents  →  OpenAI messages ──────────────────────────
def _part_text(part):
    return getattr(part, "text", None)


def _contents_to_messages(contents, system: str) -> list:
    """Translate the canonical genai `contents` (Content{role, parts}) into an OpenAI
    messages array. function_call parts (role=model) → an assistant `tool_calls` message;
    the immediately-following function_response parts (role=user) → `tool` messages. IDs are
    assigned in encounter order and consumed FIFO — matching how the loop appends a model
    turn then its tool results (bot.py:824-825)."""
    messages = [{"role": "system", "content": system}]
    pending_ids: list[str] = []
    counter = 0
    for content in contents:
        role = getattr(content, "role", "user")
        parts = getattr(content, "parts", None) or []
        if role == "model":
            texts, tool_calls = [], []
            for p in parts:
                fc = getattr(p, "function_call", None)
                if fc is not None:
                    counter += 1
                    cid = f"call_{counter}"
                    pending_ids.append(cid)
                    try:
                        args = dict(fc.args) if getattr(fc, "args", None) else {}
                    except Exception:
                        args = {}
                    tool_calls.append({"id": cid, "type": "function",
                                       "function": {"name": fc.name, "arguments": json.dumps(args, ensure_ascii=False)}})
                elif _part_text(p):
                    texts.append(_part_text(p))
            msg = {"role": "assistant", "content": "\n".join(texts) if texts else None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)
        else:  # user (or tool results)
            frs = [getattr(p, "function_response", None) for p in parts]
            frs = [fr for fr in frs if fr is not None]
            if frs:
                for fr in frs:
                    resp = getattr(fr, "response", None) or {}
                    result = resp.get("result", resp) if isinstance(resp, dict) else resp
                    cid = pending_ids.pop(0) if pending_ids else f"call_orphan_{counter}"
                    messages.append({"role": "tool", "tool_call_id": cid,
                                     "content": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)})
            else:
                texts = [_part_text(p) for p in parts if _part_text(p)]
                if texts:
                    messages.append({"role": "user", "content": "\n".join(texts)})
    return messages


# ── translation: OpenAI response  →  genai Parts (what the loop consumes) ─────
def _response_to_parts(resp):
    """OpenAI choices[0].message → real genai types.Part list so the bot loop reads it
    exactly like a Gemini response (and contents.append(Content(parts=…)) stays valid)."""
    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        parts = []
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            parts.append(types.Part(function_call=types.FunctionCall(name=tc.function.name, args=args)))
        return parts, "tool_calls", None
    content = getattr(msg, "content", None)
    if content:
        return [types.Part(text=content)], "stop", None
    return [], "empty", None


def _record_usage(resp, model: str, feature: str = "bot_fallback"):
    try:
        from src.modules import token_usage
        u = getattr(resp, "usage", None)
        if not u:
            return
        p = getattr(u, "prompt_tokens", 0) or 0
        o = getattr(u, "completion_tokens", 0) or 0
        t = getattr(u, "total_tokens", 0) or (p + o)
        token_usage.record(feature, "bot", p, o, t, model=model)
    except Exception:
        pass


# ── entry points (same (parts, finish_reason, prompt_feedback) shape as _generate_once) ─
def generate(contents, system: str, all_tools, provider: dict | None = None,
             feature: str = "bot_fallback"):
    """Run one turn-round on an OpenAI-compatible engine (a provider row, or the legacy
    FALLBACK_* env config when provider is None). Returns ([], 'ERROR', None) on any
    failure so the caller falls through to HONEST_FALLBACK — never crashes the turn.
    `feature` tags the usage: "bot" when this engine IS the user's primary, "bot_fallback"
    when it engaged as the alternate."""
    row = _row(provider)
    model = row.get("model", "")
    try:
        resp = _client(provider).chat.completions.create(
            model=model,
            messages=_contents_to_messages(contents, system),
            tools=_tool_schemas(all_tools),
            tool_choice="auto",
        )
        _record_usage(resp, model, feature)
        parts, fr, pf = _response_to_parts(resp)
        print(f"[BotFallback] model={model} finish={fr} parts={len(parts)}")
        return parts, fr, pf
    except Exception as e:
        print(f"[BotFallback] error: {e}")
        return [], "ERROR", None


def generate_text(prompt: str, provider: dict | None = None,
                  feature: str = "bot") -> str:
    """Plain text completion on the engine (no tools) — used by the bot's completion
    verifier when the user's primary is an OpenAI-compatible provider. Returns "" on
    failure (the verifier fail-safes to verdict=done)."""
    row = _row(provider)
    model = row.get("model", "")
    try:
        resp = _client(provider).chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}])
        _record_usage(resp, model, feature)
        if getattr(resp, "choices", None):
            return resp.choices[0].message.content or ""
        return ""
    except Exception as e:
        print(f"[BotFallback] generate_text error: {e}")
        return ""
