import os
import time
import tempfile
import threading
import contextvars
from contextlib import contextmanager
from google import genai
from google.genai import types
from dotenv import load_dotenv

# load_dotenv(override=True) is intentional — it forces DATA_DIR (and friends) from .env
# at import time. But override=True ALSO clobbers GEMINI_API_KEY / GEMINI_MODEL when they
# were passed explicitly on the command line, which silently sent isolated cost tests
# (scripts.measure_tokens with a local_test_key) to the PRODUCTION key/project. Preserve
# any of these that were already set in the environment, restoring them after the load.
_PRESERVE_ENV = {k: os.environ[k]
                 for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_SEARCH_TIMEOUT_SECS", "DATA_DIR",
                           "FALLBACK_API_KEY", "FALLBACK_MODEL", "FALLBACK_BASE_URL",
                           "KIMI_API_KEY", "KIMI_MODEL", "AI_DEFAULT_PROVIDER",
                           "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
                 if k in os.environ}
load_dotenv(override=True)
os.environ.update(_PRESERVE_ENV)


# Single source of truth for the Gemini model across the whole app.
# Sections read it via AIClient.model; the Teams bot imports this constant directly.
# Change the model in ONE place: this default, or the GEMINI_MODEL env var
# (lets you switch models on Railway/Azure without a redeploy).
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ── Provider registry: per-user model routing (TEXT path only) ──────────────
# The text/JSON path (generate / extract_json — ~80% of call volume) routes by the user's
# `ai_provider` setting. Search grounding, audio/video transcription, and the Files-API
# multimodal sites are CAPABILITY-PINNED to Gemini (`self.client`) — the OpenAI-compatible
# providers have no equivalent — and never route. Adding a provider = one dict row.
PROVIDERS = {
    "kimi": {
        "api": "openai",
        "base_url": "https://api.moonshot.ai/v1",
        "key_env": "KIMI_API_KEY",
        "key_env_fallback": "FALLBACK_API_KEY",   # prod has carried the Kimi key here since the bot-fallback rollout
        "model": os.getenv("KIMI_MODEL", "kimi-k2.6"),
    },
    "deepseek": {
        "api": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
        # deepseek-v4-flash = the cheap tier ($0.14/$0.28); legacy deepseek-chat alias
        # was deprecated 2026-07-24. deepseek-v4-pro is the stronger/pricier option.
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    },
    "gemini": {"api": "genai", "model": DEFAULT_GEMINI_MODEL},
}
# Platform default provider. Ships as "gemini" (zero behavior change); flipped to "kimi" on
# Railway once the graduated rollout validates. Per-user settings.ai_provider overrides it.
AI_DEFAULT_PROVIDER = os.getenv("AI_DEFAULT_PROVIDER", "gemini")


def resolve_provider(settings: dict = None, data_dir=None) -> str:
    """The user's ai_provider (from a settings dict, else data_dir/settings.json), else the
    platform default. Unknown names fall through to the default so a typo can't kill a job."""
    name = ""
    try:
        if settings and settings.get("ai_provider"):
            name = str(settings["ai_provider"]).strip().lower()
        elif data_dir is not None:
            import json as _json
            from pathlib import Path as _Path
            p = _Path(data_dir) / "settings.json"
            if p.exists():
                name = str((_json.loads(p.read_text()) or {}).get("ai_provider") or "").strip().lower()
    except Exception:
        name = ""
    if name in PROVIDERS:
        return name
    return AI_DEFAULT_PROVIDER if AI_DEFAULT_PROVIDER in PROVIDERS else "gemini"


# OpenAI-compatible client cache, keyed by base_url (mirrors bot_fallback's singleton;
# one httpx transport per endpoint for the whole process).
_OAI_CLIENTS: dict = {}
_OAI_CLIENTS_LOCK = threading.Lock()


def _openai_client(prov: dict):
    base = (prov.get("base_url") or "https://api.openai.com/v1").strip()
    cli = _OAI_CLIENTS.get(base)
    if cli is None:
        with _OAI_CLIENTS_LOCK:
            cli = _OAI_CLIENTS.get(base)
            if cli is None:
                from openai import OpenAI
                key = (os.getenv(prov.get("key_env") or "", "")
                       or os.getenv(prov.get("key_env_fallback") or "", "")).strip()
                cli = OpenAI(api_key=key, base_url=base)
                _OAI_CLIENTS[base] = cli
    return cli


# Default per-call timeouts. Text generation should always return quickly;
# video/audio transcription is heavier so callers pass a larger value.
_GEMINI_TIMEOUT_SECS = 60
# Search grounding legitimately takes longer (the model fans one prompt out into
# many underlying queries). 60s was too short → calls timed out, the SERVER still
# ran the searches (billed) but we got no response, so those searches were both
# wasted AND untraceable. Make it configurable; default keeps prior 60s behavior.
_GEMINI_SEARCH_TIMEOUT_SECS = int(os.getenv("GEMINI_SEARCH_TIMEOUT_SECS", str(_GEMINI_TIMEOUT_SECS)))


def _call_with_timeout(fn, timeout_secs: int, on_late=None):
    """Run fn() in a daemon thread, raise TimeoutError if it doesn't finish in time.

    The naive implementation `with ThreadPoolExecutor() as ex` does NOT work for
    this purpose: the executor's __exit__ calls shutdown(wait=True) which blocks
    on the worker thread even after future.result(timeout=...) raises. When the
    underlying network call is stuck (Gemini occasionally hangs without erroring),
    the worker never returns, so the `with` block never exits and the caller is
    pinned indefinitely — defeating the entire point of the timeout. We hit this
    in production: a single hung crm.py contact enrichment held the init chain
    silent for ~10 minutes before being noticed.

    Daemon thread fix: spawn fn() on its own daemon thread, join with a timeout,
    and on expiry just walk away. The thread is leaked (Python can't kill a
    blocked C-extension call from the outside) but daemon=True means it won't
    block process exit, and the underlying call will eventually hit its own TCP
    timeout. Memory leak per stuck call is acceptable since timeouts should be
    rare.
    """
    result: dict = {}
    timed_out = {"flag": False}
    def runner():
        try:
            result["value"] = fn()
        except BaseException as e:
            result["error"] = e
        finally:
            # If the main thread already gave up (timeout) but the call EVENTUALLY
            # returned, hand the late response to on_late so its token usage can still
            # be recorded — the response came back, we just used to throw it away.
            if timed_out["flag"] and on_late is not None and "value" in result:
                try:
                    on_late(result["value"])
                except Exception:
                    pass

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=timeout_secs)
    if t.is_alive():
        timed_out["flag"] = True
        raise TimeoutError(f"Gemini call exceeded {timeout_secs}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _is_quota_error(e: BaseException) -> bool:
    """True for quota / spending-cap / rate-limit errors — these must be FATAL.
    Re-sending only re-bills the input tokens (and re-issues the billable Google
    search). Matches more than the literal '429' so a spending-cap or
    RESOURCE_EXHAUSTED message is caught too — the old `"429" in err` check let those
    fall through to the generic retry and re-send up to 4×, a primary cost driver."""
    s = str(e).lower()
    return any(k in s for k in (
        "429", "resource_exhausted", "resource exhausted", "quota",
        "rate limit", "rate_limit", "spending", "billing",
    ))


# ── Token-usage attribution (P0 — cost visibility) ────────
# Callers wrap a unit of work with usage_context(feature, uid); every Gemini call
# made inside records its token usage under that tag. Read in the calling thread,
# so it resolves correctly even though the network call runs in a daemon thread.
_usage_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "ai_usage_ctx", default={"feature": "unknown", "uid": "unknown"})


@contextmanager
def usage_context(feature: str, uid: str = "unknown"):
    token = _usage_ctx.set({"feature": feature or "unknown", "uid": uid or "unknown"})
    try:
        yield
    finally:
        _usage_ctx.reset(token)


def set_usage_context(feature: str, uid: str = "unknown") -> None:
    """Non-`with` setter for thread-pool workers (call inside the worker)."""
    _usage_ctx.set({"feature": feature or "unknown", "uid": uid or "unknown"})


def current_usage_tag() -> dict:
    return dict(_usage_ctx.get())


def _extract_search_queries(response) -> list:
    """The ACTUAL Google Search queries this grounded call issued, read from
    candidates[].grounding_metadata.web_search_queries.

    This is the ONLY way to see how many BILLED searches a single call made:
    the model fans one prompt out into many underlying queries, and the search
    SKU bills per underlying query — NOT per grounded request. Capturing this is
    what lets us reconcile our own number against the Google search bill."""
    out: list = []
    try:
        for c in (getattr(response, "candidates", None) or []):
            gm = getattr(c, "grounding_metadata", None)
            wq = getattr(gm, "web_search_queries", None) if gm else None
            if wq:
                out.extend(str(q) for q in wq)
    except Exception:
        pass
    return out


def _extract_grounding_sources(response) -> list:
    """Real cited source links from candidates[].grounding_metadata.grounding_chunks[].web.{uri,title}
    — the actual pages Google returned for this grounded call (the anti-hallucination set: cite only
    from here). Returns [{title, url}]."""
    out: list = []
    try:
        for c in (getattr(response, "candidates", None) or []):
            gm = getattr(c, "grounding_metadata", None)
            for ch in (getattr(gm, "grounding_chunks", None) or []) if gm else []:
                web = getattr(ch, "web", None)
                uri = getattr(web, "uri", None) if web else None
                if uri:
                    out.append({"title": (getattr(web, "title", "") or ""), "url": str(uri)})
    except Exception:
        pass
    return out


def _record_usage(response, is_search: bool, feature_override: str | None = None,
                  model: str | None = None) -> None:
    """Best-effort: record one call's token usage — and, for grounded calls, the
    actual underlying search-query count — under the current tag.

    `model` drives per-model pricing in token_usage.cost_usd (2.5 vs 3.5 differ ~5×);
    callers pass the model that actually served the call (defaults to the app model)."""
    try:
        from src.modules import token_usage
        um = getattr(response, "usage_metadata", None)
        if um is not None:
            p = getattr(um, "prompt_token_count", 0) or 0
            o = getattr(um, "candidates_token_count", 0) or 0
            t = getattr(um, "total_token_count", 0) or (p + o)
        else:
            p = o = t = 0
        queries = _extract_search_queries(response) if is_search else []
        if um is None and not queries:
            return
        tag = _usage_ctx.get()
        token_usage.record(feature_override or tag.get("feature", "unknown"),
                           tag.get("uid", "unknown"), p, o, t,
                           is_search=is_search, search_queries=len(queries), queries=queries,
                           model=model or DEFAULT_GEMINI_MODEL)
    except Exception:
        pass


def _late_usage_recorder(tag: dict, model: str, is_search: bool):
    """Build a callback that records a LATE (post-timeout) response's usage under the
    captured tag. Used by _call_with_timeout's on_late: the daemon thread runs this when a
    timed-out call eventually returns. Contextvars don't cross threads, so feature/uid are
    captured up-front and passed explicitly. Best-effort; a truly-hung call never fires it."""
    def _rec(response):
        try:
            from src.modules import token_usage
            um = getattr(response, "usage_metadata", None)
            queries = _extract_search_queries(response) if is_search else []
            if um is None and not queries:
                return
            if um is not None:
                p = getattr(um, "prompt_token_count", 0) or 0
                o = getattr(um, "candidates_token_count", 0) or 0
                t = getattr(um, "total_token_count", 0) or (p + o)
            else:
                p = o = t = 0
            token_usage.record(tag.get("feature", "unknown"), tag.get("uid", "unknown"),
                               p, o, t, is_search=is_search,
                               search_queries=len(queries), queries=queries, model=model)
            print(f"[ai.usage] LATE-RECORDED a timed-out {'search' if is_search else 'call'} "
                  f"feature={tag.get('feature')} — captured {t} tok after the fact")
        except Exception:
            pass
    return _rec


def _budget_guard() -> None:
    """Per-user daily budget breaker: raise BudgetExceededError BEFORE an AI call if the
    current (uid, feature) is an expensive feature for an over-budget user. Cheap features
    are never blocked (degrade). No-op if the budget module/guardrail is unavailable/off."""
    try:
        from src.modules import budget
    except Exception:
        return
    budget.guard(_usage_ctx.get())  # raises budget.BudgetExceededError when blocked


class AIClient:
    def __init__(self, settings: dict = None, data_dir=None):
        # The genai client is ALWAYS constructed: the capability-pinned surfaces (search
        # grounding, audio/video transcription, and the 5 Files-API multimodal sites that
        # reach into `self.client` directly) stay on Gemini regardless of the user's
        # text-provider choice. Only the TEXT path (generate/extract_json) routes.
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = DEFAULT_GEMINI_MODEL
        self.provider = resolve_provider(settings, data_dir)
        self.text_model = PROVIDERS[self.provider]["model"]

    def generate(self, prompt: str) -> str:
        if PROVIDERS[self.provider]["api"] == "openai":
            try:
                return self._generate_openai(prompt)
            except Exception as e:
                # DeepSeek/Kimi down or refusing → cover with Gemini so a provider outage
                # never breaks a section/briefing. The genai client is always constructed.
                print(f"  [{self.provider}] text generate failed ({e}) — falling back to Gemini")
                return self._generate_gemini(prompt)
        return self._generate_gemini(prompt)

    def _generate_gemini(self, prompt: str) -> str:
        _budget_guard()
        _late = _late_usage_recorder(dict(_usage_ctx.get()), self.model, is_search=False)
        for attempt in range(2):
            try:
                response = _call_with_timeout(
                    lambda: self.client.models.generate_content(model=self.model, contents=prompt),
                    _GEMINI_TIMEOUT_SECS, on_late=_late,
                )
                text = response.text
                if not text or not text.strip():
                    if attempt < 1:
                        time.sleep(5)
                        continue
                    raise ValueError("Gemini returned empty response")
                _record_usage(response, is_search=False, model=self.model)
                return text
            except Exception as e:
                # Quota / spending-cap / rate-limit: re-sending only re-bills — fatal, no retry.
                if _is_quota_error(e):
                    raise
                # Timeout = hang. Only retry ONCE — don't waste minutes per stuck call.
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        print(f"  Gemini timeout after {_GEMINI_TIMEOUT_SECS}s, retrying once...")
                        time.sleep(3)
                        continue
                    print(f"  Gemini timeout twice — giving up.")
                    raise
                if attempt < 1:
                    time.sleep(5)
                else:
                    raise

    def _generate_openai(self, prompt: str) -> str:
        """OpenAI-compatible text path (Kimi/DeepSeek/OpenAI — whatever the provider row says).
        Mirrors the Gemini path's semantics exactly: budget guard, 2 attempts, per-call timeout,
        quota errors fatal, usage recorded under the provider's model for correct pricing."""
        _budget_guard()
        prov = PROVIDERS[self.provider]
        cli = _openai_client(prov)
        for attempt in range(2):
            try:
                resp = _call_with_timeout(
                    lambda: cli.chat.completions.create(
                        model=self.text_model,
                        messages=[{"role": "user", "content": prompt}]),
                    _GEMINI_TIMEOUT_SECS,
                )
                text = (resp.choices[0].message.content or "") if getattr(resp, "choices", None) else ""
                if not text.strip():
                    if attempt < 1:
                        time.sleep(5)
                        continue
                    raise ValueError(f"{self.provider} returned empty response")
                self._record_openai_usage(resp)
                return text
            except Exception as e:
                if _is_quota_error(e):
                    raise
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        print(f"  {self.provider} timeout after {_GEMINI_TIMEOUT_SECS}s, retrying once...")
                        time.sleep(3)
                        continue
                    print(f"  {self.provider} timeout twice — giving up.")
                    raise
                if attempt < 1:
                    time.sleep(5)
                else:
                    raise

    def _record_openai_usage(self, resp) -> None:
        """OpenAI usage shape (usage.prompt_tokens/…) → token_usage, tagged with the provider's
        model so pricing resolves correctly (mirrors bot_fallback's reader)."""
        try:
            from src.modules import token_usage
            u = getattr(resp, "usage", None)
            if not u:
                return
            tag = _usage_ctx.get()
            p = getattr(u, "prompt_tokens", 0) or 0
            o = getattr(u, "completion_tokens", 0) or 0
            t = getattr(u, "total_tokens", 0) or (p + o)
            token_usage.record(tag.get("feature", "unknown"), tag.get("uid", "unknown"),
                               p, o, t, model=self.text_model)
        except Exception:
            pass

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "recording.mp3") -> str:
        """Transcribe an audio file (mp3/m4a)."""
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            uploaded = self.client.files.upload(file=tmp_path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(5)
                uploaded = self.client.files.get(name=uploaded.name)
            for attempt in range(3):
                try:
                    # Audio transcription can legitimately take a few minutes for
                    # long meetings — 5 min ceiling per attempt is enough room
                    # while still bounding catastrophic hangs.
                    response = _call_with_timeout(
                        lambda: self.client.models.generate_content(
                            model=self.model,
                            contents=[
                                types.Part.from_uri(file_uri=uploaded.uri, mime_type="audio/mpeg"),
                                "Transcribe all speech in this audio. Label each speaker as 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                            ],
                            # Long meetings can easily exceed Gemini's default ~8K output cap;
                            # 65535 is the model max. Without this the transcript gets silently
                            # cut off and only the early portion survives.
                            config=types.GenerateContentConfig(max_output_tokens=65535),
                        ),
                        timeout_secs=300,
                    )
                    text = response.text
                    # If the model hit the output limit we still got partial text — log it
                    # so we can spot truncated meetings in the operational logs.
                    try:
                        fr = (response.candidates or [None])[0]
                        finish = getattr(fr, "finish_reason", None) if fr else None
                        if finish and str(finish).upper().endswith("MAX_TOKENS"):
                            print(f"[ai.transcribe_audio] WARN: hit MAX_TOKENS on {filename} — transcript may be truncated")
                    except Exception:
                        pass
                    if text and text.strip():
                        # Transcription bypassed the meter before this — record it so heavy
                        # meeting-audio calls show up in token accounting.
                        _record_usage(response, is_search=False, model=self.model)
                        return text
                    if attempt < 2:
                        time.sleep(5)
                except Exception as e:
                    if _is_quota_error(e):
                        raise
                    if attempt < 2:
                        time.sleep(5)
                    else:
                        raise
            raise ValueError(f"Gemini returned empty transcription for {filename}")
        finally:
            os.unlink(tmp_path)

    def transcribe_video(self, video_bytes: bytes, filename: str = "recording.mp4") -> str:
        """Upload MP4 to Gemini Files API, poll until ready, then transcribe."""
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(video_bytes)
            tmp_path = f.name
        try:
            uploaded = self.client.files.upload(file=tmp_path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(5)
                uploaded = self.client.files.get(name=uploaded.name)
            for attempt in range(3):
                try:
                    # See transcribe_audio re. 5 min ceiling.
                    response = _call_with_timeout(
                        lambda: self.client.models.generate_content(
                            model=self.model,
                            contents=[
                                types.Part.from_uri(file_uri=uploaded.uri, mime_type="video/mp4"),
                                "Transcribe all speech in this video. Label each speaker by name if visible, otherwise 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                            ],
                            # Same fix as transcribe_audio — without this Gemini truncates
                            # long meetings at the ~8K default output cap.
                            config=types.GenerateContentConfig(max_output_tokens=65535),
                        ),
                        timeout_secs=300,
                    )
                    text = response.text
                    try:
                        fr = (response.candidates or [None])[0]
                        finish = getattr(fr, "finish_reason", None) if fr else None
                        if finish and str(finish).upper().endswith("MAX_TOKENS"):
                            print(f"[ai.transcribe_video] WARN: hit MAX_TOKENS on {filename} — transcript may be truncated")
                    except Exception:
                        pass
                    if text and text.strip():
                        # See transcribe_audio — record the (heavy, multimodal) call.
                        _record_usage(response, is_search=False, model=self.model)
                        return text
                    if attempt < 2:
                        time.sleep(5)
                except Exception as e:
                    if _is_quota_error(e):
                        raise
                    if attempt < 2:
                        time.sleep(5)
                    else:
                        raise
            raise ValueError(f"Gemini returned empty transcription for {filename}")
        finally:
            os.unlink(tmp_path)

    def record_external_usage(self, response, is_search: bool = False) -> None:
        """Record usage for a call made via self.client.models.generate_content(...) directly
        (i.e. bypassing generate()/_record_usage). Attributes to the active usage_context.
        Use at the multimodal/file call sites (expenses, outreach, bulk_loader, m03, tools)
        that don't go through the metered generate* methods."""
        _record_usage(response, is_search=is_search, model=self.model)

    def generate_with_search(self, prompt: str, timeout_secs: int | None = None) -> str:
        """Generate content with Google Search grounding (real-time web search).
        Search-grounded calls can be slower than plain generate; defaults to the
        same 60s budget as generate() with one retry on timeout. Callers running a
        single rich instruction-driven search (market_intelligence) pass a larger
        timeout_secs so the search isn't chopped into generic batches to fit 60s."""
        _budget_guard()
        eff_timeout = timeout_secs or _GEMINI_SEARCH_TIMEOUT_SECS
        _late = _late_usage_recorder(dict(_usage_ctx.get()), self.model, is_search=True)
        for attempt in range(2):
            try:
                response = _call_with_timeout(
                    lambda: self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                        ),
                    ),
                    eff_timeout, on_late=_late,
                )
                _record_usage(response, is_search=True, model=self.model)
                # Empty result = "no news found" — a LEGITIMATE outcome for a search,
                # not a failure. Returning it (instead of retrying) is the core fix: the
                # old empty-retry re-issued the billable Google query up to 4× for every
                # company that simply had nothing this run — the main driver of the
                # runaway 9,129-query bill. Callers treat empty as "no items".
                return response.text or ""
            except Exception as e:
                # Quota / spending-cap / rate-limit: re-sending re-bills the search — fatal.
                if _is_quota_error(e):
                    raise
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        print(f"  Gemini search timeout after {eff_timeout}s, retrying once...")
                        time.sleep(3)
                        continue
                    print(f"  Gemini search timeout twice — giving up.")
                    # Timed-out grounded calls are the documented main source of meter
                    # undercount: the SERVER ran (and billed) the search, but we got no
                    # response → no usage_metadata. Log it so the gap is visible.
                    try:
                        from src.modules import token_usage
                        _t = _usage_ctx.get()
                        token_usage.record_failure(_t.get("feature", "unknown"),
                                                   _t.get("uid", "unknown"), kind="search-timeout")
                    except Exception:
                        pass
                    raise
                if attempt < 1:
                    time.sleep(5)
                else:
                    raise

    def generate_with_search_cited(self, prompt: str,
                                   timeout_secs: int | None = None) -> tuple[str, list]:
        """Like generate_with_search, but ALSO returns the real cited source links from the
        grounding metadata. Used by enrich to ground a background + attach guaranteed-real
        references WITHOUT a separate ddgs search (ddgs is intermittently blocked on datacenter
        IPs; Gemini grounding is the same reliable path the main search uses). Returns
        (text, [{title, url}]); ("", []) on failure is a legitimate 'nothing found' outcome —
        enrich is best-effort and must never crash the run."""
        _budget_guard()
        eff_timeout = timeout_secs or _GEMINI_SEARCH_TIMEOUT_SECS
        _late = _late_usage_recorder(dict(_usage_ctx.get()), self.model, is_search=True)
        for attempt in range(2):
            try:
                response = _call_with_timeout(
                    lambda: self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                        ),
                    ),
                    eff_timeout, on_late=_late,
                )
                _record_usage(response, is_search=True, model=self.model)
                return (response.text or ""), _extract_grounding_sources(response)
            except Exception as e:
                if _is_quota_error(e):
                    raise
                if isinstance(e, TimeoutError) and attempt < 1:
                    time.sleep(3)
                    continue
                if attempt < 1:
                    time.sleep(5)
                    continue
                return "", []

    def extract_json(self, prompt: str) -> str:
        full_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown, no code fences."
        raw = self.generate(full_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        return raw.strip()
