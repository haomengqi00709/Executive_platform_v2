"""
feeds_config — per-user feed source configuration for the intelligence sections.

Storage: .data/{user_id}/feeds.json (new, opt-in). Absent file → disabled empty
default, so behavior is unchanged until a user turns feeds on. Atomic write,
mirroring src/modules/companies.py.

Repo-level vertical presets live in data/feed_presets.json (AI/governance,
civil/construction, water/utilities, mechanical/electrical, consulting). The API
/ frontend let a user pick a preset bundle, paste arbitrary RSS URLs, and add
Google News query feeds — all credential-free public sources. Twitter/OpenBB
(which need tokens/cookies) are intentionally excluded.

Caller owns IO: load_feeds / save_feeds bookend any mutation; the section runner
only reads.
"""
import json
from pathlib import Path

_PRESETS_PATH = Path(__file__).parent.parent.parent / "data" / "feed_presets.json"


def default_feeds() -> dict:
    """Disabled empty config — what an opted-out user gets."""
    return {
        "enabled": False,
        "rss": [],          # [{name, url, enabled, category}]
        "google_news": [],  # [{name, query, enabled, category}]
        "hackernews": {"enabled": False, "fetch_top_stories": 30, "min_score": 50},
        "reddit": {"enabled": False, "subreddits": []},  # [{subreddit, enabled, sort, fetch_limit, min_score}]
    }


def load_feeds(data_dir: Path) -> dict:
    """Load .data/{uid}/feeds.json, merged over default_feeds() so missing keys
    are always present. Returns the disabled default when the file is absent or
    unreadable (fail-safe: feeds simply stay off)."""
    path = Path(data_dir) / "feeds.json"
    cfg = default_feeds()
    if not path.exists():
        return cfg
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return cfg
    if not isinstance(raw, dict):
        return cfg
    cfg.update(raw)
    # Normalize nested dicts so callers can assume shape.
    hn = cfg.get("hackernews")
    if not isinstance(hn, dict):
        cfg["hackernews"] = default_feeds()["hackernews"]
    rd = cfg.get("reddit")
    if not isinstance(rd, dict):
        cfg["reddit"] = default_feeds()["reddit"]
    for key in ("rss", "google_news"):
        if not isinstance(cfg.get(key), list):
            cfg[key] = []
    return cfg


def save_feeds(data_dir: Path, cfg: dict) -> None:
    """Atomic write to .data/{uid}/feeds.json (tmp + replace, like companies.py)."""
    path = Path(data_dir) / "feeds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    tmp.replace(path)


def load_presets() -> dict:
    """Repo-level vertical preset bundles. Empty dict if the file is missing."""
    if not _PRESETS_PATH.exists():
        return {}
    try:
        return json.loads(_PRESETS_PATH.read_text())
    except Exception:
        return {}


def apply_preset(cfg: dict, preset_key: str) -> dict:
    """Merge a preset bundle's rss + google_news feeds into a user's cfg
    (de-duped by url / query), enabling feeds. Returns the mutated cfg."""
    presets = load_presets()
    preset = presets.get(preset_key)
    if not preset:
        return cfg
    cfg.setdefault("rss", [])
    cfg.setdefault("google_news", [])
    existing_urls = {f.get("url") for f in cfg["rss"]}
    existing_queries = {f.get("query") for f in cfg["google_news"]}
    for f in preset.get("rss", []):
        if f.get("url") and f["url"] not in existing_urls:
            cfg["rss"].append({**f, "enabled": True})
            existing_urls.add(f["url"])
    for f in preset.get("google_news", []):
        if f.get("query") and f["query"] not in existing_queries:
            cfg["google_news"].append({**f, "enabled": True})
            existing_queries.add(f["query"])
    cfg["enabled"] = True
    return cfg
