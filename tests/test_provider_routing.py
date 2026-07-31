"""Per-user AI-provider routing: the TEXT path (generate/extract_json) routes by
settings.ai_provider (kimi = OpenAI-compatible, gemini = genai), default from
AI_DEFAULT_PROVIDER; capability-pinned surfaces (search/transcription/`ai.client`) stay
genai regardless. These guard: resolution order, openai-path generation + usage recording
under the Kimi model (fixes the mispricing bug), pinned invariants, and kimi pricing row."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ceo_route_test_"))
os.environ.setdefault("GEMINI_API_KEY", "dummy-offline")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import ai as ai_mod  # noqa: E402
from src.ai import AIClient, resolve_provider, PROVIDERS, DEFAULT_GEMINI_MODEL  # noqa: E402


# ── provider resolution ──────────────────────────────────────────────────────
def test_resolution_order_settings_beats_default(monkeypatch):
    monkeypatch.setattr(ai_mod, "AI_DEFAULT_PROVIDER", "gemini")
    assert resolve_provider({"ai_provider": "kimi"}) == "kimi"
    assert resolve_provider({"ai_provider": "GEMINI"}) == "gemini"   # case-insensitive
    assert resolve_provider({}) == "gemini"                          # falls to default
    assert resolve_provider(None) == "gemini"


def test_resolution_reads_settings_json_from_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mod, "AI_DEFAULT_PROVIDER", "gemini")
    (tmp_path / "settings.json").write_text(json.dumps({"ai_provider": "kimi"}))
    assert resolve_provider(data_dir=tmp_path) == "kimi"


def test_unknown_provider_falls_to_default(monkeypatch):
    monkeypatch.setattr(ai_mod, "AI_DEFAULT_PROVIDER", "gemini")
    assert resolve_provider({"ai_provider": "chatgpt-9000"}) == "gemini"   # typo can't kill a job


# ── openai text path ─────────────────────────────────────────────────────────
class FakeOAI:
    def __init__(self, content="kimi says hi"):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120))


def test_kimi_generate_routes_openai_and_records_kimi_model(monkeypatch):
    fake = FakeOAI()
    monkeypatch.setattr(ai_mod, "_openai_client", lambda prov: fake)
    recorded = {}
    def _rec(feature, uid, p, o, t, **kw):
        recorded.update(feature=feature, p=p, o=o, t=t, model=kw.get("model"))
    from src.modules import token_usage
    monkeypatch.setattr(token_usage, "record", _rec)

    c = AIClient(settings={"ai_provider": "kimi"})
    out = c.generate("hello")
    assert out == "kimi says hi"
    assert fake.calls and fake.calls[0]["model"] == PROVIDERS["kimi"]["model"]
    assert recorded["model"] == PROVIDERS["kimi"]["model"]   # priced as Kimi, not gemini fallback
    assert recorded["p"] == 100 and recorded["o"] == 20


def test_extract_json_rides_the_routed_generate(monkeypatch):
    fake = FakeOAI(content='```json\n{"a": 1}\n```')
    monkeypatch.setattr(ai_mod, "_openai_client", lambda prov: fake)
    from src.modules import token_usage
    monkeypatch.setattr(token_usage, "record", lambda *a, **k: None)
    c = AIClient(settings={"ai_provider": "kimi"})
    assert json.loads(c.extract_json("give json")) == {"a": 1}    # fences stripped, routed


def test_gemini_client_and_pinned_surface_survive_kimi_choice(monkeypatch):
    c = AIClient(settings={"ai_provider": "kimi"})
    # capability-pinned invariants: genai client still constructed, gemini model still on .model
    assert c.client is not None
    assert c.model == DEFAULT_GEMINI_MODEL
    assert c.provider == "kimi" and c.text_model == PROVIDERS["kimi"]["model"]


def test_default_constructor_is_backward_compatible(monkeypatch):
    monkeypatch.setattr(ai_mod, "AI_DEFAULT_PROVIDER", "gemini")
    c = AIClient()                                            # the 33 legacy sites' shape
    assert c.provider == "gemini" and c.text_model == DEFAULT_GEMINI_MODEL


# ── pricing row ──────────────────────────────────────────────────────────────
def test_kimi_pricing_row_no_longer_falls_back_to_gemini35():
    from src.modules.token_usage import _pricing_for, _MODEL_PRICING
    kimi = _pricing_for("kimi-k2.6")
    assert kimi is _MODEL_PRICING["kimi-k2.6"]                 # dedicated row, not fallback
    assert kimi["search"] == 0.0                               # no search SKU on Kimi
    assert _pricing_for("unknown-model") is _MODEL_PRICING["gemini-3.5-flash"]  # fallback intact


def test_deepseek_provider_registered_and_priced(monkeypatch):
    from src.ai import PROVIDERS
    from src.modules.token_usage import _pricing_for, _MODEL_PRICING
    ds = PROVIDERS["deepseek"]
    assert ds["api"] == "openai" and "deepseek.com" in ds["base_url"]
    assert ds["model"] == "deepseek-v4-flash"
    # priced from its own row, not the pricey gemini fallback (would over-report by ~10x)
    assert _pricing_for("deepseek-v4-flash") is _MODEL_PRICING["deepseek-v4-flash"]
    assert _MODEL_PRICING["deepseek-v4-flash"]["in"] < _MODEL_PRICING["gemini-2.5-flash"]["in"]


def test_openai_failure_falls_back_to_gemini(monkeypatch):
    """DeepSeek/Kimi outage must not break a section — generate() covers with Gemini."""
    monkeypatch.setattr(ai_mod, "_openai_client",
                        lambda prov: (_ for _ in ()).throw(RuntimeError("provider down")))
    from src.modules import token_usage
    monkeypatch.setattr(token_usage, "record", lambda *a, **k: None)
    c = AIClient(settings={"ai_provider": "deepseek"})
    resp = SimpleNamespace(text="gemini rescued", usage_metadata=None, candidates=[])
    c.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: resp))
    assert c.generate("hi") == "gemini rescued"      # fell back to the pinned genai client


def test_search_routes_to_deepseek_and_parses_sources(monkeypatch):
    """generate_with_search on a deepseek provider hits _search_deepseek, not Gemini grounding."""
    called = {"deepseek": 0}
    def _fake_ds(self, prompt, timeout_secs=None):
        called["deepseek"] += 1
        return "market summary", [{"title": "ENR", "url": "https://enr.com/x"}]
    monkeypatch.setattr(AIClient, "_search_deepseek", _fake_ds)
    c = AIClient(settings={"ai_provider": "deepseek"})
    assert c.generate_with_search("news?") == "market summary"
    txt, srcs = c.generate_with_search_cited("news?")
    assert txt == "market summary" and srcs[0]["url"] == "https://enr.com/x"
    assert called["deepseek"] == 2                    # both search methods routed to DeepSeek


def test_search_falls_back_to_gemini_when_deepseek_search_errors(monkeypatch):
    monkeypatch.setattr(AIClient, "_search_deepseek",
                        lambda self, p, t=None: (_ for _ in ()).throw(RuntimeError("ds search down")))
    c = AIClient(settings={"ai_provider": "deepseek"})
    # fake the pinned genai client to answer the fallback grounded call
    resp = SimpleNamespace(text="gemini grounded", usage_metadata=None, candidates=[])
    c.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: resp))
    from src.modules import token_usage
    monkeypatch.setattr(token_usage, "record", lambda *a, **k: None)
    assert c.generate_with_search("news?") == "gemini grounded"   # fell back to Gemini search


def test_gemini_user_search_stays_on_gemini(monkeypatch):
    monkeypatch.setattr(ai_mod, "AI_DEFAULT_PROVIDER", "gemini")
    monkeypatch.setattr(AIClient, "_search_deepseek",
                        lambda self, p, t=None: (_ for _ in ()).throw(AssertionError("should not call deepseek")))
    c = AIClient(settings={"ai_provider": "gemini"})
    resp = SimpleNamespace(text="g", usage_metadata=None, candidates=[])
    c.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: resp))
    from src.modules import token_usage
    monkeypatch.setattr(token_usage, "record", lambda *a, **k: None)
    assert c.generate_with_search("q") == "g"          # gemini provider never touches DeepSeek search


def test_deepseek_selectable_and_routes_openai(monkeypatch):
    fake = FakeOAI(content="deepseek routed")
    monkeypatch.setattr(ai_mod, "_openai_client", lambda prov: fake)
    from src.modules import token_usage
    rec = {}
    monkeypatch.setattr(token_usage, "record",
                        lambda f, u, p, o, t, **k: rec.update(model=k.get("model")))
    c = AIClient(settings={"ai_provider": "deepseek"})
    assert c.provider == "deepseek" and c.generate("hi") == "deepseek routed"
    assert fake.calls[0]["model"] == "deepseek-v4-flash"
    assert rec["model"] == "deepseek-v4-flash"                 # priced as DeepSeek
    assert c.client is not None                                # gemini pinned surface intact
