"""
relationship_health section — Scheduled

Surfaces CRM contacts whose engagement pattern needs attention.
Detection is rule-based (NOT AI): we compute email metrics over a 90-day window
and classify each contact's health by deterministic thresholds. The AI's only
job is to translate the metrics into a human-readable reminder + suggested_action.

Healthy contacts are not surfaced — items only contains at_risk / cooling / stalled / new.

Data sources:
  crm.json          → candidate contacts (client/prospect/partner, not ignored)
  projects.json     → related active/at_risk/stalled projects per contact
  Graph inbox (90d) → inbound metadata (from, receivedDateTime)
  Graph sent  (90d) → outbound metadata (toRecipients, sentDateTime)

Does NOT use screener — only metadata (sender + date), no email content.
"""
import hashlib
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.validator import validate_output
from src.modules.profile import load_profile_context

_SKILLS_DIR = Path(__file__).parent.parent / "skills" / "relationship_health"
_RESULT_ID = "relationship_health"

_AUTO_CRM_STATUSES = {"client", "prospect", "partner", "investor"}
_ACTIVE_PROJECT_STATUSES = {"ongoing", "needs_attention", "paused", "early_stage"}

_LOOKBACK_DAYS = 90
_WINDOW = 30  # current vs previous 30-day window

_AT_RISK_DROP_PCT = -70
_AT_RISK_DAYS = 21
_COOLING_DROP_PCT = -50
_COOLING_DAYS = 14
_STALLED_DAYS = 30
_NEW_WINDOW_DAYS = 14

_BATCH_SIZE = 5

_DEFAULT_INSTRUCTION = """\
# Relationship Health — Reminder Style

The system surfaces contacts whose engagement metrics indicate they need
attention. The detection rules have already decided who to surface — your
job is only to control the tone and emphasis of the reminders.

## Tone
- Direct and specific. No fluff.
- Reference real numbers (e.g. "down from 12 to 2 emails").
- If a related project exists, mention it by name. If not, focus on the
  engagement pattern itself.

## What to emphasise
- Active client relationships where engagement has dropped sharply
- Outstanding replies the user owes
- New prospects worth a warm follow-up
- Stalled threads where the user is waiting on a reply

## Keep all surfaced contacts
- All contacts in this list passed rule-based filters (cooling / at_risk /
  stalled / new). Do not remove them for lacking an active project — many
  important relationships exist outside of formally-tracked projects.
- Only remove a contact if you have a clear reason (e.g. they are clearly
  internal noise that slipped through CRM, an obvious automated address,
  or a one-off contact that shouldn't have been classified as client/prospect/partner).
"""


def _load_skill_doc() -> str:
    path = _SKILLS_DIR / "skill.md"
    return path.read_text().strip() if path.exists() else ""


def _load_user_instruction(data_dir: Path) -> str:
    path = data_dir / "instructions" / "relationship_health.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_INSTRUCTION)
        return _DEFAULT_INSTRUCTION.strip()
    return path.read_text().strip()


def _build_candidates(crm_data: dict) -> list[dict]:
    out: list[dict] = []
    for email, contact in crm_data.get("contacts", {}).items():
        if contact.get("ignore") or contact.get("archived") or contact.get("priority") == "ignore":
            continue
        if contact.get("priority") == "low":
            continue
        status = contact.get("status", "other")
        if status not in _AUTO_CRM_STATUSES:
            continue
        out.append({
            "email":   email.lower(),
            "name":    contact.get("name") or email,
            "company": contact.get("company") or "",
            "status":  status,
        })
    return out


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _group_inbox(inbox: list[dict]) -> dict[str, list[datetime]]:
    """Map lowercased sender → sorted list of receivedDateTime."""
    out: dict[str, list[datetime]] = {}
    for m in inbox:
        addr = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
        dt = _parse_dt(m.get("receivedDateTime") or "")
        if not addr or not dt:
            continue
        out.setdefault(addr, []).append(dt)
    for addrs in out.values():
        addrs.sort()
    return out


def _group_sent(sent: list[dict]) -> dict[str, list[datetime]]:
    """Map lowercased recipient → sorted list of sentDateTime. Each message
    contributes one entry per recipient address."""
    out: dict[str, list[datetime]] = {}
    for m in sent:
        dt = _parse_dt(m.get("sentDateTime") or "")
        if not dt:
            continue
        for rcpt in m.get("toRecipients", []) or []:
            addr = ((rcpt or {}).get("emailAddress") or {}).get("address", "").lower()
            if not addr:
                continue
            out.setdefault(addr, []).append(dt)
    for addrs in out.values():
        addrs.sort()
    return out


def _compute_metrics(
    email: str,
    inbox_index: dict[str, list[datetime]],
    sent_index: dict[str, list[datetime]],
    now: datetime,
) -> dict:
    """Compute current vs previous 30-day window metrics for a contact."""
    in_dates  = inbox_index.get(email, [])
    out_dates = sent_index.get(email, [])

    cur_start  = now - timedelta(days=_WINDOW)
    prev_start = now - timedelta(days=_WINDOW * 2)

    in_30d      = sum(1 for d in in_dates  if d >= cur_start)
    in_prev_30d = sum(1 for d in in_dates  if prev_start <= d < cur_start)
    out_30d     = sum(1 for d in out_dates if d >= cur_start)
    out_prev_30d = sum(1 for d in out_dates if prev_start <= d < cur_start)

    last_in  = in_dates[-1]  if in_dates  else None
    last_out = out_dates[-1] if out_dates else None

    days_since_in  = (now - last_in).days  if last_in  else None
    days_since_out = (now - last_out).days if last_out else None

    # Trend: % change vs prev window. None if no prior data.
    if in_prev_30d == 0:
        trend_pct = None if in_30d == 0 else 100
    else:
        trend_pct = int(round((in_30d - in_prev_30d) / in_prev_30d * 100))

    # Awaiting my reply: last inbound is later than last outbound (they spoke last)
    awaiting_my_reply = bool(last_in and (not last_out or last_in > last_out))

    return {
        "emails_in_30d":      in_30d,
        "emails_in_prev_30d": in_prev_30d,
        "emails_out_30d":     out_30d,
        "emails_out_prev_30d": out_prev_30d,
        "last_inbound":       last_in.date().isoformat() if last_in else None,
        "last_outbound":      last_out.date().isoformat() if last_out else None,
        "days_since_inbound":  days_since_in,
        "days_since_outbound": days_since_out,
        "trend_pct":          trend_pct,
        "awaiting_my_reply":  awaiting_my_reply,
    }


def _classify_health(metrics: dict, has_active_project: bool) -> tuple[str, str]:
    """Return (health, priority). Returns ('healthy', '') if no concern."""
    in_30d       = metrics["emails_in_30d"]
    in_prev_30d  = metrics["emails_in_prev_30d"]
    trend        = metrics["trend_pct"]
    days_since_in = metrics["days_since_inbound"]
    awaiting     = metrics["awaiting_my_reply"]

    # New: first contact in current window, none in prior
    if in_prev_30d == 0 and in_30d > 0:
        # Also require recent contact within the new window
        if days_since_in is not None and days_since_in <= _NEW_WINDOW_DAYS:
            return ("new", "medium")

    # Stalled: long silence with us holding the ball
    if days_since_in is not None and days_since_in >= _STALLED_DAYS and not awaiting:
        return ("stalled", "high" if has_active_project else "medium")

    # At risk: steep drop + tied to an active project + recent silence
    if (trend is not None and trend <= _AT_RISK_DROP_PCT
            and has_active_project
            and days_since_in is not None and days_since_in >= _AT_RISK_DAYS):
        return ("at_risk", "high")

    # Cooling: meaningful drop + a couple weeks quiet
    if (trend is not None and trend <= _COOLING_DROP_PCT
            and days_since_in is not None and days_since_in >= _COOLING_DAYS):
        return ("cooling", "high" if has_active_project else "medium")

    return ("healthy", "")


def _link_projects(email: str, projects_data: dict) -> list[dict]:
    out = []
    for proj in projects_data.get("projects", {}).values():
        if proj.get("ignore") or proj.get("archived"):
            continue
        if proj.get("status") not in _ACTIVE_PROJECT_STATUSES:
            continue
        participants = [p.lower() for p in (proj.get("participants") or [])]
        if email not in participants:
            continue
        out.append({
            "id":            proj.get("id", ""),
            "name":          proj.get("name", ""),
            "status":        proj.get("status", ""),
            "momentum":      proj.get("momentum", ""),
            "last_activity": proj.get("last_activity", ""),
        })
    return out


def _format_for_ai(item: dict) -> str:
    """Compact text block describing one item for the AI prompt."""
    m = item["metrics"]
    projects = item.get("related_projects") or []
    if projects:
        proj_lines = "\n".join(
            f"  - {p['name']} (status: {p['status']}, momentum: {p.get('momentum') or 'n/a'})"
            for p in projects
        )
    else:
        proj_lines = "  - (none)"

    return (
        f"Contact: {item['contact_name']} <{item['contact_email']}>\n"
        f"Company: {item['company'] or '—'} ({item['status']})\n"
        f"Rule-determined health: {item['health']} (priority: {item['priority']})\n"
        f"Metrics:\n"
        f"  - Emails in (last 30d / prev 30d): {m['emails_in_30d']} / {m['emails_in_prev_30d']}"
        + (f" (trend {m['trend_pct']:+d}%)" if m['trend_pct'] is not None else "") + "\n"
        f"  - Emails out (last 30d / prev 30d): {m['emails_out_30d']} / {m['emails_out_prev_30d']}\n"
        f"  - Last inbound: {m['last_inbound'] or 'never'}"
        + (f" ({m['days_since_inbound']}d ago)" if m['days_since_inbound'] is not None else "") + "\n"
        f"  - Last outbound: {m['last_outbound'] or 'never'}"
        + (f" ({m['days_since_outbound']}d ago)" if m['days_since_outbound'] is not None else "") + "\n"
        f"  - Awaiting my reply: {m['awaiting_my_reply']}\n"
        f"Related active projects:\n{proj_lines}"
    )


def _generate_reminders(
    items: list[dict],
    ai: AIClient,
    skill_doc: str,
    user_instruction: str,
    display_name: str,
    date_str: str,
    business_context: str,
    progress,
) -> list[dict]:
    """Call AI in batches of 5 to attach reminder + suggested_action to each item.
    On failure, the item gets fallback text derived from its metrics."""
    skill_filled = (
        skill_doc
        .replace("{display_name}", display_name)
        .replace("{date}", date_str)
        .replace("{user_instruction}", user_instruction)
    )
    context_block = f"Business context:\n{business_context}\n\n" if business_context else ""

    out: list[dict] = []
    for batch_idx in range(0, len(items), _BATCH_SIZE):
        batch = items[batch_idx : batch_idx + _BATCH_SIZE]
        blocks = "\n\n---\n\n".join(_format_for_ai(it) for it in batch)

        prompt = (
            f"You are writing concise relationship-health reminders for {display_name}. "
            f"Today is {date_str}.\n\n"
            f"{context_block}{skill_filled}\n\n"
            f"--- USER INSTRUCTION ---\n{user_instruction}\n--- END ---\n\n"
            f"Below are {len(batch)} contact(s). Each already has a rule-determined health "
            f"label — do NOT change it. Your job is ONLY to write:\n"
            f'  - "reminder": 1-2 sentences explaining the engagement pattern. Use real numbers '
            f"from the metrics. If a related project exists, mention it by name.\n"
            f'  - "suggested_action": 1 specific next step. Reference the project if relevant. '
            f'Be concrete (e.g., "Check in re: Apex Q3 Deal status this week" — not "Reach out").\n\n'
            f"Return ONLY a JSON array with one object per contact, in order:\n"
            f"[\n"
            f'  {{"contact_email": "...", "reminder": "...", "suggested_action": "..."}}\n'
            f"]\n\n"
            f"--- CONTACTS ---\n{blocks}\n--- END ---"
        )

        if progress:
            progress(f"  AI batch {batch_idx // _BATCH_SIZE + 1}/{(len(items) + _BATCH_SIZE - 1) // _BATCH_SIZE} "
                     f"({len(batch)} contact(s))")

        decisions_by_email: dict[str, dict] = {}
        try:
            raw = ai.extract_json(prompt)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for d in parsed:
                    if isinstance(d, dict) and d.get("contact_email"):
                        decisions_by_email[d["contact_email"].lower()] = d
        except Exception as e:
            if progress:
                progress(f"  AI batch failed: {e} — using fallback text")

        for it in batch:
            d = decisions_by_email.get(it["contact_email"].lower())
            if d:
                it["reminder"] = str(d.get("reminder") or "")[:400]
                it["suggested_action"] = str(d.get("suggested_action") or "")[:300]
            else:
                m = it["metrics"]
                it["reminder"] = (
                    f"{it['contact_name']} engagement: {m['emails_in_30d']} emails in last 30d "
                    f"vs {m['emails_in_prev_30d']} prior."
                )
                it["suggested_action"] = "Review and decide if a check-in is warranted."
            out.append(it)

    return out


def _assign_id(item: dict) -> dict:
    key = item["contact_email"] + "|" + item["health"]
    return {**item, "id": hashlib.sha1(key.encode()).hexdigest()[:16]}


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "": 3}
_HEALTH_RANK   = {"at_risk": 0, "stalled": 1, "cooling": 2, "new": 3}


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
        print(f"[relationship_health] {msg}")

    data_dir = Path(data_dir)
    results_path = data_dir / "results" / f"{_RESULT_ID}.json"
    display_name = settings.get("display_name") or "the executive"
    business_context = load_profile_context(data_dir)
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    now = datetime.now(timezone.utc)

    skill_doc = _load_skill_doc()
    user_instruction = _load_user_instruction(data_dir)

    crm_data: dict = {}
    crm_path = data_dir / "crm.json"
    if crm_path.exists():
        try:
            crm_data = json.loads(crm_path.read_text())
        except Exception:
            crm_data = {}

    projects_data: dict = {}
    proj_path = data_dir / "projects.json"
    if proj_path.exists():
        try:
            projects_data = json.loads(proj_path.read_text())
        except Exception:
            projects_data = {}

    candidates = _build_candidates(crm_data)
    if not candidates:
        _p("No CRM candidates (client/prospect/partner) — skipping")
        result = {
            "id": _RESULT_ID,
            "status": "not_run",
            "last_run": now.isoformat(),
            "items": [],
            "count": 0,
            "empty": True,
            "empty_reason": "no_candidates",
        }
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    _p(f"Evaluating {len(candidates)} CRM contact(s) (last {_LOOKBACK_DAYS}d)")

    _p("Fetching inbox metadata...")
    try:
        inbox = graph.get_inbox_metadata_since(days=_LOOKBACK_DAYS, max_results=2000)
    except Exception as e:
        _p(f"Inbox fetch failed: {e}")
        inbox = []

    _p("Fetching sent metadata...")
    try:
        sent = graph.get_sent_messages_since(days=_LOOKBACK_DAYS, max_results=2000)
    except Exception as e:
        _p(f"Sent fetch failed: {e}")
        sent = []

    inbox_index = _group_inbox(inbox)
    sent_index = _group_sent(sent)

    needs_attention: list[dict] = []
    for c in candidates:
        metrics = _compute_metrics(c["email"], inbox_index, sent_index, now)
        related = _link_projects(c["email"], projects_data)
        health, priority = _classify_health(metrics, has_active_project=bool(related))
        if health == "healthy":
            continue
        item = {
            "contact_email": c["email"],
            "contact_name":  c["name"],
            "company":       c["company"],
            "status":        c["status"],
            "health":        health,
            "priority":      priority,
            "metrics":       metrics,
            "related_projects": related,
        }
        needs_attention.append(item)

    _p(f"{len(needs_attention)} contact(s) need attention "
       f"(filtered out {len(candidates) - len(needs_attention)} healthy)")

    if not needs_attention:
        result = {
            "id": _RESULT_ID,
            "status": "fresh",
            "last_run": now.isoformat(),
            "items": [],
            "count": 0,
            "empty": True,
        }
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    needs_attention.sort(key=lambda x: (
        _PRIORITY_RANK.get(x["priority"], 9),
        _HEALTH_RANK.get(x["health"], 9),
    ))

    items = _generate_reminders(
        needs_attention, ai, skill_doc, user_instruction,
        display_name, date_str, business_context, progress,
    )

    items = [_assign_id(it) for it in items]

    items = validate_output(
        items, ai,
        section_id=_RESULT_ID,
        user_instruction=user_instruction,
        display_name=display_name,
        date_str=date_str,
    )

    result = {
        "id": _RESULT_ID,
        "status": "fresh",
        "last_run": now.isoformat(),
        "items": items,
        "count": len(items),
        "empty": len(items) == 0,
        "candidates_evaluated": len(candidates),
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _p(f"Done — {len(items)} item(s) saved")
    return result
