"""
feeds_fetch — pull public feed items into the intelligence-section item schema.

Synchronous (the section runner is sync). All source types are public and
credential-free:
  - plain RSS/Atom      (user-pasted or preset trade-press URLs; ${ENV} subst for
                         rare token feeds, adapted from Horizon scrapers/rss.py)
  - Google News RSS     (news.google.com/rss/search?q=... — turns ANY topic into a
                         feed; the universal adapter for niche engineering verticals
                         with no dedicated trade-press RSS)
  - Hacker News         (public Firebase API)
  - Reddit              (public .json, .rss fallback + User-Agent; no OAuth)

Output dicts match what _normalise() in the section expects: headline, summary,
signal_type ("other" pre-scoring), source, source_url, published_date, relevance.
intel_score then rates each for relevance to the reader and the gate drops the
off-target majority — so a wide net here is fine.

Per-source try/except: one bad feed can't sink the run. Items are capped to keep
the downstream scoring cost bounded.
"""
import html
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TIMEOUT = 15.0
_PER_FEED_MAX = 15      # entries kept per single feed
_TOTAL_MAX = 60         # hard cap on feed items per run (controls scoring cost)
_TAG_RE = re.compile(r"<[^>]+>")
_ENV_RE = re.compile(r"\$\{(\w+)\}")
_HN_BASE = "https://hacker-news.firebaseio.com/v0"


def _noop(_msg: str) -> None:
    pass


def _clean(text: str, limit: int = 600) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _entry_dt(entry) -> "datetime | None":
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
            except Exception:
                continue
    return None


def _date_str(dt: "datetime | None") -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _item(headline, summary, source, url, published_date) -> dict:
    return {
        "headline": (headline or "").strip(),
        "summary": summary or "",
        "signal_type": "other",   # reassigned by feed_rewrite before the validator
        "source": source or "",
        "source_url": url or "",
        "published_date": published_date or "",
        "relevance": "",
        "origin": "feed",         # marks raw-news items so they get rewritten to brief format
    }


def _subst_env(url: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), url or "")


def _parse_feed_bytes(content: bytes, source_name: str, since: datetime) -> list[dict]:
    parsed = feedparser.parse(content)
    out = []
    for entry in parsed.entries[: _PER_FEED_MAX * 2]:
        dt = _entry_dt(entry)
        if dt and dt < since:
            continue
        title = entry.get("title", "").strip()
        if not title:
            continue
        # Google News (and some RSS) carry the real publisher in <source>; prefer
        # it so the item's source is a credible publication name, not the query
        # label "Google News: …" (which the validator rejects as non-credible).
        src = source_name
        ent_src = entry.get("source")
        if isinstance(ent_src, dict) and ent_src.get("title"):
            src = ent_src["title"]
        # Google News titles are "Headline - Publisher"; strip the suffix.
        if src and title.endswith(f" - {src}"):
            title = title[: -len(f" - {src}")].strip()
        summary = _clean(entry.get("summary") or entry.get("description") or "")
        out.append(_item(title, summary, src, entry.get("link", ""), _date_str(dt)))
        if len(out) >= _PER_FEED_MAX:
            break
    return out


def _fetch_rss(client: httpx.Client, feed: dict, since: datetime, log) -> list[dict]:
    url = _subst_env(str(feed.get("url") or ""))
    if not url:
        return []
    name = feed.get("name") or url
    try:
        resp = client.get(url)
        resp.raise_for_status()
        items = _parse_feed_bytes(resp.content, name, since)
        log(f"  feed RSS '{name}': {len(items)}")
        return items
    except Exception as e:
        log(f"  feed RSS '{name}' failed: {e}")
        return []


def _fetch_google_news(client: httpx.Client, gn: dict, since: datetime, log) -> list[dict]:
    query = (gn.get("query") or "").strip()
    if not query:
        return []
    name = gn.get("name") or query
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        items = _parse_feed_bytes(resp.content, f"Google News: {name}", since)
        log(f"  feed GoogleNews '{name}': {len(items)}")
        return items
    except Exception as e:
        log(f"  feed GoogleNews '{name}' failed: {e}")
        return []


def _fetch_hackernews(client: httpx.Client, hn: dict, since: datetime, log) -> list[dict]:
    top_n = int(hn.get("fetch_top_stories") or 30)
    min_score = int(hn.get("min_score") or 50)
    out: list[dict] = []
    try:
        ids = client.get(f"{_HN_BASE}/topstories.json").json()[:top_n]
    except Exception as e:
        log(f"  feed HN failed: {e}")
        return []
    for sid in ids:
        try:
            s = client.get(f"{_HN_BASE}/item/{sid}.json").json()
        except Exception:
            continue
        if not s or s.get("type") != "story" or (s.get("score", 0) < min_score):
            continue
        dt = datetime.fromtimestamp(s.get("time", 0), tz=timezone.utc) if s.get("time") else None
        if dt and dt < since:
            continue
        disc = f"https://news.ycombinator.com/item?id={sid}"
        out.append(_item(s.get("title", ""), _clean(s.get("text", "")),
                         "Hacker News", s.get("url") or disc, _date_str(dt)))
        if len(out) >= _PER_FEED_MAX:
            break
    log(f"  feed HN: {len(out)}")
    return out


def _fetch_reddit_sub(client: httpx.Client, sub: dict, since: datetime, log) -> list[dict]:
    name = (sub.get("subreddit") or "").strip().lstrip("r/").strip("/")
    if not name:
        return []
    sort = sub.get("sort") or "hot"
    limit = int(sub.get("fetch_limit") or 15)
    min_score = int(sub.get("min_score") or 30)
    out: list[dict] = []
    # Primary: public JSON
    try:
        resp = client.get(f"https://www.reddit.com/r/{name}/{sort}.json",
                          params={"limit": limit, "raw_json": 1})
        if resp.status_code == 200:
            for child in resp.json().get("data", {}).get("children", []):
                p = child.get("data", {})
                if p.get("score", 0) < min_score:
                    continue
                dt = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc) if p.get("created_utc") else None
                if dt and dt < since:
                    continue
                disc = "https://www.reddit.com" + p.get("permalink", "")
                url = disc if p.get("is_self") else (p.get("url") or disc)
                out.append(_item(p.get("title", ""), _clean(p.get("selftext", "")),
                                 f"Reddit r/{name}", url, _date_str(dt)))
                if len(out) >= _PER_FEED_MAX:
                    break
            log(f"  feed Reddit r/{name}: {len(out)}")
            return out
    except Exception:
        pass
    # Fallback: public RSS (Reddit sometimes 403s the JSON endpoint)
    try:
        resp = client.get(f"https://www.reddit.com/r/{name}/{sort}/.rss")
        resp.raise_for_status()
        out = _parse_feed_bytes(resp.content, f"Reddit r/{name}", since)
        log(f"  feed Reddit r/{name} (rss): {len(out)}")
    except Exception as e:
        log(f"  feed Reddit r/{name} failed: {e}")
    return out


def fetch_feed_items(feeds_cfg: dict, since: datetime, log=None) -> list[dict]:
    """Fetch all enabled feed sources, return item-schema dicts (uncapped by
    relevance — scoring does that downstream). Returns [] when feeds are off."""
    log = log or _noop
    if not feeds_cfg or not feeds_cfg.get("enabled"):
        return []

    items: list[dict] = []
    with httpx.Client(follow_redirects=True, timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        for feed in feeds_cfg.get("rss", []):
            if feed.get("enabled", True):
                items.extend(_fetch_rss(client, feed, since, log))
        for gn in feeds_cfg.get("google_news", []):
            if gn.get("enabled", True):
                items.extend(_fetch_google_news(client, gn, since, log))
        hn = feeds_cfg.get("hackernews") or {}
        if hn.get("enabled"):
            items.extend(_fetch_hackernews(client, hn, since, log))
        reddit = feeds_cfg.get("reddit") or {}
        if reddit.get("enabled"):
            for sub in reddit.get("subreddits", []):
                if sub.get("enabled", True):
                    items.extend(_fetch_reddit_sub(client, sub, since, log))

    if len(items) > _TOTAL_MAX:
        log(f"  feeds: capping {len(items)} → {_TOTAL_MAX}")
        items = items[:_TOTAL_MAX]
    return items
