"""
business_insights section — Scheduled (weekly brief)

Meta-section: aggregates from other sections' results to produce a weekly
executive brief. Does NOT call Graph API, does NOT re-analyse emails. Reads
only .data/{uid}/results/*.json plus crm.json / projects.json.

Output:
  - stats: this_week + prev_week + deltas (numeric dashboard)
  - items: 3-7 rule-surfaced headlines, categorised (pipeline / engagement /
    execution / intel)
  - narrative: a 3-5 sentence paragraph written by AI tying it all together

History:
  .data/{uid}/business_insights_history.json — last 4 weekly snapshots, used
  to compute week-over-week deltas.
"""
import hashlib
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.profile import load_profile_context
from src.modules.tz import now_local

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "business_insights"
_RESULT_ID = "business_insights"
_HISTORY_FILE = "business_insights_history.json"
_MAX_SNAPSHOTS = 4

# Section IDs we pull metrics from
_SOURCE_SECTIONS = [
    "reply_needed", "followup_needed",
    "commitments_extract", "upcoming_commitments",
    "relationship_health",
    "recent_meetings", "meeting_action_items",
    "expenses",
    "market_intelligence", "company_intelligence",
]

_DEFAULT_INSTRUCTION = """\
# Business Insights — Weekly Brief Style

This section aggregates the week's activity into a short executive digest.
Customise tone here.

## Tone
- Direct and informational. Not consulting-speak.
- Use real numbers from the aggregated metrics.
- Reference specific companies or contacts when relevant.

## Emphasis
- Concrete events and changes, not generic observations.
- Connect the dots across categories (pipeline → execution).
- Surface concerns and opportunities, not platitudes.
"""


def _load_skill_doc() -> str:
    path = _SKILLS_DIR / "skill.md"
    return path.read_text().strip() if path.exists() else ""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / "business_insights.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _read_section(data_dir: Path, section_id: str) -> dict:
    path = data_dir / "results" / f"{section_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _last_complete_week(data_dir: Path) -> tuple[date, date]:
    """(Monday, Sunday) of the most recently COMPLETED week, in the user's
    timezone. period_end = the most recent Sunday STRICTLY before today;
    period_start = that Monday. Run Monday morning → the week that just ended
    (e.g. run Mon Jun 8 → Jun 1–7). A mid-week run still returns the last fully
    ended week, so the report is never a half-finished current week."""
    today = now_local(data_dir).date()
    period_end = today - timedelta(days=today.weekday() + 1)   # last Sunday < today
    period_start = period_end - timedelta(days=6)              # that Monday
    return period_start, period_end


def _period_label(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{start:%b %-d} – {end:%b %-d, %Y}"
    return f"{start:%b %-d, %Y} – {end:%b %-d, %Y}"


def _filter_by_period(items: list, start: date, end: date, date_field: str) -> list:
    """Items whose date_field (YYYY-MM-DD or ISO datetime) is in [start, end]."""
    s, e = start.isoformat(), end.isoformat()
    return [it for it in (items or []) if s <= (it.get(date_field) or "")[:10] <= e]


def _meetings_in_period(sources: dict, start: date, end: date) -> list[dict]:
    """Meetings held in [start, end]. Prefer the recent_meetings result; if it's
    missing/empty (its cache file is intermittently not regenerated), derive the
    distinct meetings from meeting_action_items — both are views of the SAME wiki
    meeting DB, so this is not a cross-source fallback."""
    rm = _filter_by_period(sources.get("recent_meetings", {}).get("items", []), start, end, "date")
    if rm:
        return rm
    seen, derived = set(), []
    for it in _filter_by_period(sources.get("meeting_action_items", {}).get("items", []),
                                start, end, "meeting_date"):
        key = it.get("meeting_id") or (it.get("meeting_title"), it.get("meeting_date"))
        if key in seen:
            continue
        seen.add(key)
        derived.append({"title": it.get("meeting_title") or "", "date": it.get("meeting_date") or ""})
    return derived


def _count_open_commitments(commitments_extract: dict) -> int:
    """Open = not marked done and not snoozed."""
    return sum(
        1 for it in commitments_extract.get("items", [])
        if it.get("state") not in ("done", "snoozed") and not it.get("completed")
    )


def _count_due_this_week(upcoming: dict, today: date) -> int:
    week_end = today + timedelta(days=7)
    n = 0
    for it in upcoming.get("items", []):
        d = it.get("due_date", "")
        if not d:
            continue
        try:
            due = date.fromisoformat(d[:10])
        except Exception:
            continue
        if today <= due <= week_end:
            n += 1
    return n


def _count_health(rh: dict, label: str) -> int:
    return sum(1 for it in rh.get("items", []) if it.get("health") == label)


def _count_priority(items: list, priority: str) -> int:
    return sum(1 for it in items if it.get("priority") == priority)


def _crm_stats(crm: dict) -> dict:
    contacts = crm.get("contacts", {})
    out = {"client": 0, "prospect": 0, "partner": 0, "investor": 0,
           "vendor": 0, "internal": 0, "other": 0}
    for c in contacts.values():
        if c.get("ignore") or c.get("archived"):
            continue
        s = c.get("status", "other")
        out[s] = out.get(s, 0) + 1
    return out


def _projects_stats(projects_data: dict) -> dict:
    out = {"ongoing": 0, "needs_attention": 0, "paused": 0, "early_stage": 0, "completed": 0}
    for p in projects_data.get("projects", {}).values():
        if p.get("ignore") or p.get("archived"):
            continue
        s = p.get("status", "")
        if s in out:
            out[s] += 1
    return out


def _new_crm_in_period(crm: dict, start: date, end: date) -> int:
    """Contacts updated within [start, end] AND status client/prospect/partner/investor."""
    s, e = start.isoformat(), end.isoformat()
    n = 0
    for c in crm.get("contacts", {}).values():
        if c.get("ignore") or c.get("archived"):
            continue
        if c.get("status") not in ("client", "prospect", "partner", "investor"):
            continue
        if s <= (c.get("updated_at") or "")[:10] <= e:
            n += 1
    return n


def _compute_this_week_stats(data_dir: Path, period_start: date, period_end: date, today: date) -> dict:
    sources = {sid: _read_section(data_dir, sid) for sid in _SOURCE_SECTIONS}
    crm = _read_json(data_dir / "crm.json")
    projects = _read_json(data_dir / "projects.json")

    crm_counts = _crm_stats(crm)
    proj_counts = _projects_stats(projects)

    rh = sources["relationship_health"]
    market_items = sources["market_intelligence"].get("items", [])
    company_items = sources["company_intelligence"].get("items", [])

    # Retrospective metrics — filtered to the report's week [period_start,
    # period_end], NOT each source's own 14/21-day window. This is the fix for
    # "the weekly report shows last week's meetings": meetings/action items/
    # expenses/new contacts now match the labeled week exactly.
    meetings_period = _meetings_in_period(sources, period_start, period_end)
    actions_period  = _filter_by_period(sources["meeting_action_items"].get("items", []),
                                        period_start, period_end, "meeting_date")
    expenses_period = _filter_by_period(sources["expenses"].get("items", []),
                                        period_start, period_end, "date")

    return {
        # ── current state (point-in-time backlog / snapshot, NOT week-filtered) ──
        "emails_reply_needed":      sources["reply_needed"].get("count", 0),
        "emails_followup_needed":   sources["followup_needed"].get("count", 0),
        "commitments_open":         _count_open_commitments(sources["commitments_extract"]),
        "relationships_at_risk":    _count_health(rh, "at_risk"),
        "relationships_cooling":    _count_health(rh, "cooling"),
        "relationships_stalled":    _count_health(rh, "stalled"),
        "relationships_new":        _count_health(rh, "new"),
        "market_signals":           len(market_items),
        "market_signals_high":      _count_priority(market_items, "high"),
        "company_signals":          len(company_items),
        "company_signals_high":     _count_priority(company_items, "high"),
        "crm_clients":              crm_counts.get("client", 0),
        "crm_prospects":            crm_counts.get("prospect", 0),
        "crm_partners":             crm_counts.get("partner", 0),
        "projects_ongoing":         proj_counts.get("ongoing", 0),
        "projects_needs_attention": proj_counts.get("needs_attention", 0),
        "projects_paused":          proj_counts.get("paused", 0),
        "projects_early_stage":     proj_counts.get("early_stage", 0),
        # ── last week (retrospective, filtered to [period_start, period_end]) ──
        "meetings_recent":          len(meetings_period),
        "action_items_open":        len(actions_period),
        "expenses_captured":        len(expenses_period),
        "crm_new_this_week":        _new_crm_in_period(crm, period_start, period_end),
        # ── week ahead (forward 7 days from today) ──
        "commitments_due_this_week": _count_due_this_week(sources["upcoming_commitments"], today),
    }


def _load_history(data_dir: Path) -> list[dict]:
    data = _read_json(data_dir / _HISTORY_FILE)
    snaps = data.get("snapshots", []) if isinstance(data, dict) else []
    return snaps if isinstance(snaps, list) else []


def _save_history(data_dir: Path, snapshots: list[dict]) -> None:
    trimmed = snapshots[-_MAX_SNAPSHOTS:]
    (data_dir / _HISTORY_FILE).write_text(
        json.dumps({"snapshots": trimmed}, indent=2)
    )


def _compute_deltas(this_week: dict, prev: dict | None) -> dict:
    if not prev:
        return {}
    deltas = {}
    for key, cur in this_week.items():
        if not isinstance(cur, (int, float)):
            continue
        prior = prev.get(key, 0)
        if not isinstance(prior, (int, float)):
            continue
        delta = cur - prior
        if prior == 0:
            pct = None if cur == 0 else 100
        else:
            pct = int(round((cur - prior) / prior * 100))
        deltas[key] = {"current": cur, "previous": prior, "delta": delta, "pct": pct}
    return deltas


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _build_headlines(
    stats: dict,
    deltas: dict,
    sources: dict,
    period_start: date,
    period_end: date,
) -> list[dict]:
    """Rule-driven: returns 3-7 structured headlines. No AI. Each is tagged with
    a `timeframe`: 'past' (last week's activity), 'now' (current backlog/state),
    or 'ahead' (next 7 days) — the formatter groups by these."""
    headlines: list[dict] = []

    def add(category, title, detail, priority, evidence, timeframe="now"):
        headlines.append({
            "category": category,
            "timeframe": timeframe,
            "title": title,
            "detail": detail,
            "priority": priority,
            "evidence": evidence,
            "type": "headline",
        })

    rh_items = sources.get("relationship_health", {}).get("items", [])
    rep_items = sources.get("reply_needed", {}).get("items", [])
    fup_items = sources.get("followup_needed", {}).get("items", [])
    up_items = sources.get("upcoming_commitments", {}).get("items", [])
    mk_items = sources.get("market_intelligence", {}).get("items", [])
    co_items = sources.get("company_intelligence", {}).get("items", [])
    rm_items = _meetings_in_period(sources, period_start, period_end)
    exp_items = _filter_by_period(sources.get("expenses", {}).get("items", []),
                                  period_start, period_end, "date")

    # ── pipeline ────────────────────────────────────────────
    if stats.get("crm_new_this_week", 0) > 0:
        add("pipeline",
            f"{stats['crm_new_this_week']} new contact(s) added",
            "New client / prospect / partner contacts in CRM during the week.",
            "medium",
            ["crm.json"],
            "past")

    if stats.get("crm_prospects", 0) > 0:
        add("pipeline",
            f"{stats['crm_prospects']} active prospect(s) in CRM",
            f"Across {stats.get('crm_clients', 0)} clients and {stats.get('crm_partners', 0)} partners.",
            "low",
            ["crm.json"],
            "now")

    # ── engagement (current backlog / relationship state) ───
    at_risk = [it for it in rh_items if it.get("health") == "at_risk"]
    if at_risk:
        top = at_risk[0]
        detail = f"{top.get('contact_name', '')} ({top.get('company', '')}) — {top.get('reminder', '')[:200]}"
        add("engagement",
            f"{len(at_risk)} client relationship(s) at risk",
            detail,
            "high",
            ["relationship_health"],
            "now")

    cooling = [it for it in rh_items if it.get("health") == "cooling"]
    if cooling:
        prev = (deltas.get("relationships_cooling") or {}).get("previous")
        if prev is not None and prev > 0:
            change = deltas["relationships_cooling"]["delta"]
            if change > 0:
                trend = f" (up {change} vs last week)"
            elif change < 0:
                trend = f" (down {abs(change)} vs last week)"
            else:
                trend = " (unchanged from last week)"
        else:
            trend = ""
        first_names = ", ".join(
            (c.get("contact_name") or "?").split()[0]
            for c in cooling[:3]
        )
        add("engagement",
            f"{len(cooling)} contact(s) cooling{trend}",
            f"Top: {first_names}." if first_names else "",
            "medium",
            ["relationship_health"],
            "now")

    if rep_items:
        top = rep_items[0]
        add("engagement",
            f"{len(rep_items)} email(s) awaiting your reply",
            f"Top: \"{(top.get('subject') or '')[:80]}\" from {top.get('from_name') or top.get('from_email') or '—'}.",
            "high" if any(it.get("priority") == "high" for it in rep_items) else "medium",
            ["reply_needed"],
            "now")

    if fup_items:
        add("engagement",
            f"{len(fup_items)} email(s) you sent without a reply",
            f"Top: \"{(fup_items[0].get('subject') or '')[:80]}\" to {fup_items[0].get('to_name') or fup_items[0].get('to_email') or '—'}.",
            "medium",
            ["followup_needed"],
            "now")

    # ── week ahead (next 7 days) ─────────────────────────────
    due_soon = stats.get("commitments_due_this_week", 0)
    if due_soon > 0:
        sample_titles = [
            (it.get("description") or "")[:60]
            for it in up_items[:3]
        ]
        sample_block = "; ".join(t for t in sample_titles if t)
        add("execution",
            f"{due_soon} commitment(s) due in the next 7 days",
            sample_block or "See upcoming_commitments for details.",
            "high",
            ["upcoming_commitments"],
            "ahead")

    # ── last week's execution (meetings / expenses) ──────────
    if stats.get("meetings_recent", 0) > 0:
        ai_count = stats.get("action_items_open", 0)
        recent_subjects = [
            (m.get("subject") or m.get("title") or "")[:60]
            for m in rm_items[:3]
        ]
        recent_block = "; ".join(s for s in recent_subjects if s)
        add("execution",
            f"{stats['meetings_recent']} meeting(s) this week — {ai_count} action item(s)",
            recent_block or "See recent_meetings for details.",
            "low",
            ["recent_meetings", "meeting_action_items"],
            "past")

    if stats.get("expenses_captured", 0) > 0:
        add("execution",
            f"{stats['expenses_captured']} receipt(s) captured",
            f"Latest: {(exp_items[0].get('vendor') or '?') if exp_items else '?'}.",
            "low",
            ["expenses"],
            "past")

    # ── intel (current signals) ─────────────────────────────
    if stats.get("company_signals_high", 0) > 0:
        top = next((it for it in co_items if it.get("priority") == "high"), None)
        if top:
            add("intel",
                f"{stats['company_signals_high']} high-priority company signal(s)",
                f"Top: {top.get('company', '')} — {(top.get('headline') or '')[:160]}",
                "high",
                ["company_intelligence"],
                "now")

    if stats.get("market_signals_high", 0) > 0:
        top = next((it for it in mk_items if it.get("priority") == "high"), None)
        if top:
            add("intel",
                f"{stats['market_signals_high']} high-priority market signal(s)",
                f"Top: {(top.get('headline') or '')[:160]}",
                "high",
                ["market_intelligence"],
                "now")

    headlines.sort(key=lambda h: _PRIORITY_RANK.get(h["priority"], 9))

    for h in headlines:
        key = h["category"] + "|" + h["title"]
        h["id"] = hashlib.sha1(key.encode()).hexdigest()[:16]

    return headlines


def _format_summary_for_ai(stats: dict, deltas: dict, headlines: list[dict]) -> str:
    """Compact text block summarising data for the narrative AI call."""
    lines = ["## This week's metrics"]
    for k, v in stats.items():
        d = deltas.get(k)
        if d and d.get("delta") is not None:
            delta_str = f" (was {d['previous']}, delta {d['delta']:+d}"
            if d.get("pct") is not None:
                delta_str += f", {d['pct']:+d}%)"
            else:
                delta_str += ")"
            lines.append(f"  - {k}: {v}{delta_str}")
        else:
            lines.append(f"  - {k}: {v}")

    lines.append("")
    lines.append("## Rule-surfaced headlines (with priority)")
    for h in headlines:
        lines.append(f"  [{h['priority'].upper()}/{h['category']}] {h['title']}")
        if h.get("detail"):
            lines.append(f"     {h['detail']}")

    return "\n".join(lines)


def _generate_narrative(
    stats: dict,
    deltas: dict,
    headlines: list[dict],
    ai: AIClient,
    skill_doc: str,
    user_instruction: str,
    display_name: str,
    date_str: str,
    week_of: str,
    business_context: str,
) -> str:
    if not headlines and all(v == 0 for v in stats.values() if isinstance(v, int)):
        return ""

    summary = _format_summary_for_ai(stats, deltas, headlines)
    skill_filled = (
        skill_doc
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{week_of}", week_of)
        .replace("{user_instruction}", user_instruction)
    )
    context_block = f"Business context:\n{business_context}\n\n" if business_context else ""

    prompt = (
        f"You are writing a 3-5 sentence weekly executive brief for {display_name}.\n"
        f"Today is {date_str}. This is a retrospective of the week of {week_of} that\n"
        f"just ended (what happened last week), plus a short note on what's coming up.\n\n"
        f"{context_block}{skill_filled}\n\n"
        f"--- USER INSTRUCTION ---\n{user_instruction}\n--- END ---\n\n"
        f"{summary}\n\n"
        f"Write a single paragraph (3-5 sentences) connecting the dots across categories.\n"
        f"Use real numbers from the data. Reference companies / contacts by name where helpful.\n"
        f"Do not introduce any claim that isn't in the data above.\n"
        f"Return ONLY the paragraph — no markdown, no headers, no bullets."
    )

    try:
        raw = ai.generate(prompt).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return raw[:1500]
    except Exception as e:
        print(f"[business_insights] Narrative AI failed: {e}")
        return ""


def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict,
    progress=None,
    force_refresh: bool = False,
) -> dict:
    def _p(msg: str):
        if progress:
            progress(msg)
        print(f"[business_insights] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    display_name = settings.get("display_name") or "the executive"
    business_context = load_profile_context(data_dir)
    today = now_local(data_dir).date()
    period_start, period_end = _last_complete_week(data_dir)
    period_label = _period_label(period_start, period_end)
    week_of = period_start.isoformat()   # back-compat key for history dedup
    date_str = now_local(data_dir).strftime("%A, %B %d, %Y")
    now = datetime.now(timezone.utc)

    skill_doc = _load_skill_doc()
    user_instruction = _load_user_instruction(data_dir)

    _p(f"Aggregating weekly brief for {period_label}")

    sources = {sid: _read_section(data_dir, sid) for sid in _SOURCE_SECTIONS}
    this_week = _compute_this_week_stats(data_dir, period_start, period_end, today)

    total_signal = sum(v for v in this_week.values() if isinstance(v, int))
    if total_signal == 0:
        result = {
            "id": _RESULT_ID,
            "status": "not_run",
            "last_run": now.isoformat(),
            "week_of": week_of,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "period_label": period_label,
            "narrative": "",
            "stats": {"this_week": this_week, "prev_week": None, "deltas": {}},
            "items": [],
            "count": 0,
            "empty": True,
            "empty_reason": "no_upstream_data",
        }
        results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        _p("No upstream data — skipping")
        return result

    history = _load_history(data_dir)
    prev_snapshot = history[-1] if history else None
    prev_week_stats = prev_snapshot.get("stats") if prev_snapshot else None

    deltas = _compute_deltas(this_week, prev_week_stats)
    _p(f"Computed {len(deltas)} delta(s) vs week of {prev_snapshot.get('week_of') if prev_snapshot else 'n/a'}")

    headlines = _build_headlines(this_week, deltas, sources, period_start, period_end)
    _p(f"Surfaced {len(headlines)} headline(s)")

    _p("Generating narrative...")
    narrative = _generate_narrative(
        this_week, deltas, headlines, ai,
        skill_doc, user_instruction,
        display_name, date_str, period_label, business_context,
    )

    history.append({
        "week_of": week_of,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "captured_at": now.isoformat(),
        "stats": this_week,
    })
    _save_history(data_dir, history)

    result = {
        "id": _RESULT_ID,
        "status": "fresh",
        "last_run": now.isoformat(),
        "week_of": week_of,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_label": period_label,
        "narrative": narrative,
        "stats": {
            "this_week": this_week,
            "prev_week": prev_week_stats,
            "deltas": deltas,
        },
        "items": headlines,
        "count": len(headlines),
        "empty": len(headlines) == 0,
    }

    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(headlines)} headline(s) saved")
    return result
