"""
Per-user daily spend cap (graceful degrade) — P0 cost guardrail.

Layered UNDER the Google monthly project cap (the hard backstop): this stops ONE user from
running away, attributes cost to the (multi-tenant) billing/plan model, and contains the blast
radius of any future regression to a single user's daily allowance.

Behaviour = DEGRADE: when a user's accumulated cost for the UTC day reaches their plan's daily
budget, only the EXPENSIVE features (search / thinking / full-scan heavy) are blocked for the
rest of the day; the cheap features (bot chat, reply drafts, commitments, …) keep working.

Spend is tracked per-user in .data/{uid}/_usage/spend.json, incremented by the token meter
(src/modules/token_usage.record → add_spend). Enforced in src/ai.AIClient.generate* via guard().
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Plan → daily budget (USD). Set per user via settings.json "plan"; override the $ directly
# with settings "daily_budget_usd". Tiers per product decision 2026-06-17.
PLAN_DAILY_USD = {"trial": 0.50, "standard": 2.00, "pro": 5.00}
# Default plan for users without one set — generous enough not to break normal 2.5 usage
# (a full 2.5 daily pass is ~$0.85). Override with env DEFAULT_PLAN.
DEFAULT_PLAN = os.getenv("DEFAULT_PLAN", "standard")

# Features blocked once a user is over budget (the search / thinking / scan-heavy ones).
# Everything NOT in this set keeps working when over budget (= the "degrade" behaviour).
EXPENSIVE_FEATURES = {
    "company_intelligence", "market_intelligence", "business_insights",
    "projects_refresh", "projects_build", "crm_refresh", "m03_meeting",
}

# Turn the whole guardrail off with BUDGET_ENABLED=0 (spend is still tracked).
_ENABLED = os.getenv("BUDGET_ENABLED", "1").strip().lower() not in ("0", "false", "no")

_RETAIN_DAYS = 10


class BudgetExceededError(Exception):
    """Raised before an AI call when an over-budget user requests an expensive feature."""
    def __init__(self, uid: str, feature: str, spent: float, budget: float):
        self.uid, self.feature, self.spent, self.budget = uid, feature, spent, budget
        super().__init__(
            f"daily budget exceeded for {(uid or '')[:8]} "
            f"(${spent:.2f}/${budget:.2f}) — '{feature}' blocked (cheap features still run)")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _data_dir() -> Path:
    try:
        from src import auth
        return Path(auth.DATA_DIR)
    except Exception:
        return Path(os.getenv("DATA_DIR") or (Path(__file__).resolve().parents[2] / ".data"))


def _spend_path(uid: str) -> Path:
    return _data_dir() / uid / "_usage" / "spend.json"


def _trackable(uid: str) -> bool:
    return bool(uid) and uid not in ("unknown",)


def add_spend(uid: str, feature: str, usd: float, in_tok: int = 0, out_tok: int = 0) -> None:
    """Add one call's cost + tokens to the user's UTC-day tally — both the day total and a
    per-feature breakdown (for the ops dashboard). Best-effort; never raises into callers.

    Day record shape: {"usd","in","out","calls","by_feature": {feat: {usd,in,out,calls}}}.
    The reserved "_grant" key (admin overrides) lives alongside the day records."""
    if not _trackable(uid):
        return
    try:
        p = _spend_path(uid)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(p.read_text()) if p.exists() else {}
        today = _today()
        d = data.get(today)
        if not isinstance(d, dict):  # init (or migrate an old bare-float record)
            d = {"usd": float(d) if isinstance(d, (int, float)) else 0.0,
                 "in": 0, "out": 0, "calls": 0, "by_feature": {}}
            data[today] = d
        usd = float(usd or 0); in_tok = int(in_tok or 0); out_tok = int(out_tok or 0)
        d["usd"] = round(d.get("usd", 0.0) + usd, 6)
        d["in"] = d.get("in", 0) + in_tok
        d["out"] = d.get("out", 0) + out_tok
        d["calls"] = d.get("calls", 0) + 1
        bf = d.setdefault("by_feature", {}).setdefault(
            feature or "unknown", {"usd": 0.0, "in": 0, "out": 0, "calls": 0})
        bf["usd"] = round(bf["usd"] + usd, 6); bf["in"] += in_tok
        bf["out"] += out_tok; bf["calls"] += 1
        # prune old day records (keep "_grant")
        cutoff = datetime.now(timezone.utc).date().toordinal() - _RETAIN_DAYS
        for k in [k for k in list(data) if k != "_grant" and _ordinal(k) and _ordinal(k) < cutoff]:
            data.pop(k, None)
        from src.storage import atomic_write_json
        atomic_write_json(p, data)
    except Exception:
        pass


def today_usage(uid: str) -> dict:
    """The user's full UTC-day usage record: {usd, in, out, calls, by_feature}."""
    try:
        p = _spend_path(uid)
        if p.exists():
            d = json.loads(p.read_text()).get(_today())
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {"usd": 0.0, "in": 0, "out": 0, "calls": 0, "by_feature": {}}


def _ordinal(date_str: str):
    try:
        return datetime.fromisoformat(date_str).date().toordinal()
    except Exception:
        return None


def today_spend(uid: str) -> float:
    try:
        p = _spend_path(uid)
        if p.exists():
            d = json.loads(p.read_text()).get(_today())
            if isinstance(d, dict):
                return float(d.get("usd", 0.0))
            if isinstance(d, (int, float)):
                return float(d)
    except Exception:
        pass
    return 0.0


def _read_settings(uid: str) -> dict:
    try:
        sp = _data_dir() / uid / "settings.json"
        return json.loads(sp.read_text()) if sp.exists() else {}
    except Exception:
        return {}


def daily_budget(uid: str, settings: dict | None = None) -> float:
    """The user's daily $ allowance: explicit settings 'daily_budget_usd', else plan tier."""
    s = settings if settings is not None else _read_settings(uid)
    if isinstance(s.get("daily_budget_usd"), (int, float)) and s["daily_budget_usd"] > 0:
        return float(s["daily_budget_usd"])
    plan = (s.get("plan") or DEFAULT_PLAN).strip().lower()
    return PLAN_DAILY_USD.get(plan, PLAN_DAILY_USD["standard"])


def status(uid: str, settings: dict | None = None) -> dict:
    """For the ops dashboard / bot: where the user stands today — $ AND tokens, per-feature."""
    u = today_usage(uid)
    spent = float(u.get("usd", 0.0))
    base = daily_budget(uid, settings)
    eff = effective_budget(uid, settings)
    return {
        "uid": uid, "date": _today(),
        "spent_usd": round(spent, 4), "budget_usd": base, "effective_budget_usd": round(eff, 4),
        "remaining_usd": round(max(0.0, eff - spent), 4), "grant_usd": round(grant_today(uid), 4),
        "in_tokens": u.get("in", 0), "out_tokens": u.get("out", 0), "calls": u.get("calls", 0),
        "by_feature": u.get("by_feature", {}),
        "over": spent >= eff, "plan": (_read_settings(uid).get("plan") or DEFAULT_PLAN),
    }


# ── Admin overrides (unblock) ─────────────────────────────
# A "grant" is extra $ allowance for ONE UTC day, stored in the user's spend.json under the
# reserved "_grant" key {date: extra_usd}. unblock_today() with no amount grants effectively
# unlimited for today; with an amount it tops up. Plan/budget changes are durable (settings).

def grant_today(uid: str) -> float:
    try:
        p = _spend_path(uid)
        if p.exists():
            return float(json.loads(p.read_text()).get("_grant", {}).get(_today(), 0.0))
    except Exception:
        pass
    return 0.0


def effective_budget(uid: str, settings: dict | None = None) -> float:
    return daily_budget(uid, settings) + grant_today(uid)


def unblock_today(uid: str, extra_usd: float | None = None) -> dict:
    """Admin: lift today's block for a user. extra_usd=None → effectively unlimited today;
    a number → top up today's allowance by that much. Durable upgrades use set_plan()."""
    try:
        p = _spend_path(uid)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(p.read_text()) if p.exists() else {}
        grant = data.setdefault("_grant", {})
        grant[_today()] = 1e9 if extra_usd is None else float(grant.get(_today(), 0.0)) + float(extra_usd)
        from src.storage import atomic_write_json
        atomic_write_json(p, data)
    except Exception:
        pass
    return status(uid)


def set_plan(uid: str, plan: str) -> dict:
    """Admin: durably change a user's plan tier (trial/standard/pro)."""
    return _update_settings(uid, {"plan": plan, "daily_budget_usd": None})


def set_daily_budget(uid: str, usd: float) -> dict:
    """Admin: durably set an explicit daily $ budget (overrides plan tier)."""
    return _update_settings(uid, {"daily_budget_usd": float(usd)})


def _update_settings(uid: str, changes: dict) -> dict:
    try:
        sp = _data_dir() / uid / "settings.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        s = json.loads(sp.read_text()) if sp.exists() else {}
        for k, v in changes.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        from src.storage import atomic_write_json
        atomic_write_json(sp, s)
    except Exception:
        pass
    return status(uid)


# ── Block events / admin notification ─────────────────────
_notifier = None            # optional callback(event_dict) wired by the app (e.g. Teams push)
_notified_today: set = set()  # in-process dedup: (uid, date) already logged/notified today


def set_notifier(fn) -> None:
    """App wires a callback here at startup to push block events somewhere (Teams/email).
    Keeps budget.py decoupled from graph/bot."""
    global _notifier
    _notifier = fn


def _events_path() -> Path:
    return _data_dir() / "_ops" / "budget_events.jsonl"


def _record_block_event(uid: str, feature: str, spent: float, budget: float) -> None:
    """Once per (uid, UTC day): append a durable event + fire the notifier. Best-effort."""
    keyt = (uid, _today())
    if keyt in _notified_today:
        return
    _notified_today.add(keyt)
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "uid": uid,
          "feature": feature, "spent_usd": round(spent, 4), "budget_usd": round(budget, 4),
          "plan": (_read_settings(uid).get("plan") or DEFAULT_PLAN)}
    try:
        p = _events_path(); p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if _notifier:
        try:
            _notifier(ev)
        except Exception:
            pass


def recent_block_events(hours: float = 24) -> list:
    """For the admin view: who hit their cap recently."""
    try:
        p = _events_path()
        if not p.exists():
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        out = []
        for ln in p.read_text().splitlines():
            try:
                ev = json.loads(ln)
                if datetime.fromisoformat(ev["ts"]).timestamp() >= cutoff:
                    out.append(ev)
            except Exception:
                continue
        return out
    except Exception:
        return []


def should_block(uid: str, feature: str, settings: dict | None = None) -> bool:
    """True iff an over-budget user is requesting an EXPENSIVE feature (→ degrade).
    Accounts for admin grants (unblock_today)."""
    if not _ENABLED or not _trackable(uid):
        return False
    if feature not in EXPENSIVE_FEATURES:
        return False  # cheap features always allowed (the degrade)
    return today_spend(uid) >= effective_budget(uid, settings)


def guard(tag: dict) -> None:
    """Raise BudgetExceededError before an AI call if the current (uid, feature) is an
    expensive feature for an over-budget user. Logs/notifies once per user per day."""
    uid = (tag or {}).get("uid")
    feature = (tag or {}).get("feature") or "unknown"
    if should_block(uid, feature):
        _record_block_event(uid, feature, today_spend(uid), effective_budget(uid))
        raise BudgetExceededError(uid, feature, today_spend(uid), effective_budget(uid))
