"""
Slash command handler for the Teams bot.

Activated when a message starts with '/'. Runs before all existing bot logic
and returns immediately — the main conversation flow is never touched.

Commands
--------
/help                              list available commands
/context                           status of all 5 profile documents
/context [slug]                    view a specific document
/context [slug] [instruction]      refine a document with AI
/settings                          current settings snapshot

Slug names: business_profile · writing_style · market_segments
            ai_instructions · file_naming
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SLUGS: dict[str, str] = {
    "business_profile": "🏢 Business Profile",
    "writing_style":    "✍️  Writing Style Guide",
    "market_segments":  "🎯 Market Segments",
    "ai_instructions":  "🤖 AI Instructions",
    "file_naming":      "📁 Standards & Naming",
}

SKILL_SLUGS: dict[str, str] = {
    "morning_briefing_skill":       "☀️ Morning Briefing Skill",
    "reply_needed_skill":           "📬 Reply Needed Skill",
    "followup_needed_skill":        "📤 Follow-up Needed Skill",
    "invoices_contracts_skill":     "🧾 Invoices & Contracts Skill",
    "commitments_extract_skill":    "📋 Commitments Extract Skill",
    "upcoming_commitments_skill":   "📅 Upcoming Commitments Skill",
    "recent_meetings_skill":        "🤝 Recent Meetings Skill",
    "meeting_action_items_skill":   "✅ Meeting Action Items Skill",
    "relationship_health_skill":    "💚 Relationship Health Skill",
    "business_insights_skill":      "📊 Business Insights Skill",
    "market_intel_skill":           "🌐 Market Intel Skill",
}

ALL_SLUGS: dict[str, str] = {**SLUGS, **SKILL_SLUGS}

_HELP = """\
📋 Context docs
  /context — status of all 5 profile documents
  /context [slug] — view a document
  /context [slug] [instruction] — refine with AI

📰 Market Intelligence focus
  /context market_intel_focus — show current BI industry focus
  /context market_intel_focus [industries] — set focus, e.g. equipment manufacturing, water utilities
  /context market_intel_focus reset — revert to all industries

⚙️ Settings
  /settings — current settings snapshot

  /help — show this message

Slugs: business_profile · writing_style · market_segments · ai_instructions · file_naming\
"""


def handle(text: str, context_path, settings_path, ai=None) -> str:
    """
    Main entry point. Parse the slash command and dispatch.
    context_path and settings_path may be str or Path or None.
    """
    ctx  = Path(context_path)  if context_path  else None
    sett = Path(settings_path) if settings_path else None

    parts = text.strip().split(maxsplit=2)
    cmd   = parts[0].lower()

    if cmd in ("/help", "/?"):
        return _HELP

    if cmd == "/context":
        return _context(parts[1:], ctx, sett, ai)

    if cmd == "/settings":
        return _settings(sett)

    if cmd == "/focus":
        return _focus(parts[1:], sett)

    return f"Unknown command `{cmd}`. Type `/help` to see available commands."


# ── /context ──────────────────────────────────────────────────────────────────

def _context(args: list, ctx: "Path | None", sett: "Path | None", ai) -> str:

    # Special case: market_intel_focus lives in settings.json, not context docs
    if args and args[0].lower() == "market_intel_focus":
        s       = _read_json(sett)
        current = (s.get("market_intel_focus") or "").strip()
        if len(args) == 1:
            if current:
                return (
                    f"📰 Market Intelligence focus: {current}\n\n"
                    f"/context market_intel_focus [industries] to change\n"
                    f"/context market_intel_focus reset to track all industries"
                )
            return (
                "📰 Market Intelligence focus: all industries (default)\n\n"
                "/context market_intel_focus [industries] to narrow, e.g.:\n"
                "  /context market_intel_focus equipment manufacturing, water utilities"
            )
        value = " ".join(args[1:]).strip() if len(args) >= 2 else ""
        if value.lower() == "reset":
            s["market_intel_focus"] = ""
            _write_json(sett, s)
            return "✅ Market Intelligence reset — next briefing will cover all industries from your Company Profiles."
        return _context_intent(f"change my BI to {value}", _read_json(ctx), _read_json(ctx).get("documents", {}), ctx, sett, ai)

    data = _read_json(ctx)
    docs = data.get("documents", {})

    # /context — list all docs
    if not args:
        lines = ["📋 Profile Documents\n"]
        for slug, title in SLUGS.items():
            doc     = docs.get(slug, {})
            content = doc.get("content", "")
            if content:
                preview = next(
                    (l.strip() for l in content.splitlines()
                     if l.strip() and not l.startswith("#")),
                    "",
                )
                updated = (doc.get("updated_at") or "")[:10]
                lines.append(f"✅ {title} ({updated})\n   {preview[:80]}")
            else:
                lines.append(f"⬜ {title} — not set")
        focus = (_read_json(sett).get("market_intel_focus") or "").strip()
        focus_line = f"✅ Market Intelligence Focus: {focus}" if focus else "⬜ Market Intelligence Focus — all industries (default)"
        lines.append(f"\n{focus_line}")
        lines.append(
            "\n/context [slug] to view\n"
            "/context [slug] [instruction] to update\n"
            "/context market_intel_focus [industries] to set BI focus"
        )
        return "\n".join(lines)

    slug = args[0].lower()
    if slug not in ALL_SLUGS:
        full_text = " ".join(args)
        return _context_intent(full_text, data, docs, ctx, sett, ai)

    doc     = docs.get(slug, {})
    content = doc.get("content", "")
    title   = ALL_SLUGS[slug]

    # /context [slug] — view
    if len(args) == 1:
        if not content:
            return (
                f"⬜ {title} — not set\n\n"
                f"Go to the Context page in the frontend to generate it.\n"
                f"Then use /context {slug} [instruction] to refine via chat."
            )
        updated = (doc.get("updated_at") or "")[:10]
        preview = content[:1200] + ("…" if len(content) > 1200 else "")
        return f"{title} (updated {updated})\n\n{preview}"

    # /context [slug] [instruction] — refine with AI
    instruction = args[1]

    if not content:
        return (
            f"⬜ {title} has no content to refine yet.\n\n"
            f"Generate it via the frontend first, then use "
            f"/context {slug} [instruction] to refine."
        )
    if not ai:
        return "⚠️ AI unavailable right now — try again in a moment."
    if not ctx:
        return "⚠️ Context path not configured for this account."

    from src.modules.context_docs import refine_document
    try:
        updated_content = refine_document(slug, content, instruction, ai)
    except Exception as e:
        return f"❌ Failed to refine document: {e}"

    docs[slug] = {
        "slug":       slug,
        "content":    updated_content,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    data["documents"] = docs
    _write_json(ctx, data)

    if slug in ("business_profile", "writing_style") and sett:
        _sync_settings(slug, updated_content, sett)
    elif slug in SKILL_SLUGS and sett:
        from src.modules.context_docs import extract_settings_fields
        fields = extract_settings_fields({slug: updated_content})
        s_data = _read_json(sett)
        s_data.update(fields)
        _write_json(sett, s_data)

    preview = updated_content[:600] + ("…" if len(updated_content) > 600 else "")
    return (
        f"✅ {title} updated.\n\n"
        f"Preview:\n{preview}\n\n"
        f"Type /context {slug} to see the full document."
    )


# ── /settings ─────────────────────────────────────────────────────────────────

def _settings(sett: "Path | None") -> str:
    from src.modules.profile import load_profile_context
    s = _read_json(sett)

    name    = s.get("display_name") or "—"
    email   = s.get("report_email") or "—"
    webhook = s.get("teams_webhook_url") or ""
    data_dir = sett.parent if sett else None
    bc      = load_profile_context(data_dir) if data_dir else ""
    ws      = s.get("writing_style_note") or ""
    focus   = s.get("briefing_focus") or ""

    wh_disp = "✅ configured" if webhook else "⬜ not set"
    bc_disp = bc[:300] if bc else "⬜ not set — edit profile/business_profile.md and profile/market_segments.md"
    ws_disp = ws[:150] if ws else "⬜ not set — save a Writing Style doc to populate"

    return (
        f"⚙️ Current Settings\n\n"
        f"Name: {name}\n"
        f"Report Email: {email}\n"
        f"Teams Webhook: {wh_disp}\n\n"
        f"Profile (injected into AI):\n{bc_disp}\n\n"
        f"Writing Style Note (injected into AI):\n{ws_disp}\n\n"
        f"Briefing Focus: {focus or '(default)'}"
    )


# ── /context natural language fallback ────────────────────────────────────────

def _get_available_industries(sett: "Path | None") -> list:
    """Load unique industry tags from the user's companies.json."""
    if not sett:
        return []
    try:
        path = sett.parent / "companies.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        industries = sorted({
            c.get("industry", "").strip()
            for c in data.get("companies", {}).values()
            if c.get("industry", "").strip()
        })
        return industries
    except Exception:
        return []


def _context_intent(text: str, ctx_data: dict, docs: dict, ctx: "Path | None",
                    sett: "Path | None", ai) -> str:
    """Parse free-form /context instructions via AI and dispatch to the right action."""
    if not ai:
        return (
            f"⚠️ Can't parse '{text}' — AI unavailable.\n"
            f"Use exact syntax: /context [slug] [instruction]\n"
            f"Slugs: {' · '.join(SLUGS.keys())} · market_intel_focus"
        )

    doc_list      = "\n".join(f'  "{s}" — {t}' for s, t in ALL_SLUGS.items())
    s_data        = _read_json(sett)
    current_focus = (s_data.get("market_intel_focus") or "").strip() or "all industries (default)"
    industries    = _get_available_industries(sett)
    ind_section   = (
        f"Available industries in Company Profiles: {', '.join(industries)}"
        if industries else
        "No Company Profiles set up yet — any industry name will be accepted."
    )

    prompt = f"""You are parsing a user's configuration instruction for an executive AI platform.

Available actions:
1. update_doc — update a profile document or skill document
   Valid slugs: {list(ALL_SLUGS.keys())}
   Documents:
{doc_list}

2. update_focus — set the Market Intelligence industry focus (which industries appear in daily briefing)
   Current focus: {current_focus}
   {ind_section}
   For update_focus, also assess whether the requested industry matches the available ones:
     - "matched": exact or very close match found — use the canonical name from the list
     - "suggest": plausible but not exact — provide 1-3 closest suggestions from the list
     - "not_found": no reasonable match — list available options
     - "no_profiles": no Company Profiles exist yet — accept any value

3. reset_focus — reset Market Intelligence to cover all industries

4. view_focus — show current Market Intelligence focus

5. view_doc — view a specific document

6. update_skill_param — change a skill configuration parameter
   Use when the user mentions specific numbers, days, contacts, or briefing style.
   Valid parameters (param → what it controls):
   - reply_after_days: days before unanswered inbound emails are flagged (default 1)
   - reply_urgent_days: days before flagging as urgent (default 14)
   - followup_after_days: days before sent emails with no reply are flagged (default 3)
   - followup_urgent_days: days before follow-up marked urgent (default 14)
   - upcoming_commitments_days: how many days ahead to show commitments (default 7)
   - upcoming_commitments_urgent_days: days threshold for urgent commitments (default 2)
   - bi_lookback_days: days of email/meeting history for business intelligence (default 30)
   - bi_top_contacts: number of top contacts to analyse (default 10)
   - bi_active_days: days threshold for "active" relationship status (default 30)
   - bi_atrisk_days: days threshold for "at-risk" relationship status (default 60)
   - briefing_style: morning briefing length — concise | detailed | bullets (default: concise)
   Examples: "follow-up after 3 days" → followup_after_days=3
             "track my top 20 contacts" → bi_top_contacts=20
             "make my briefing detailed" → briefing_style=detailed

User instruction: "{text}"

Return JSON only — choose one:
{{"action": "update_doc", "slug": "<slug>", "instruction": "<what to change>"}}
{{"action": "update_focus", "value": "<requested value>", "match": "matched", "canonical": "<exact industry name from list>"}}
{{"action": "update_focus", "value": "<requested value>", "match": "suggest", "suggestions": ["<closest 1>", "<closest 2>"]}}
{{"action": "update_focus", "value": "<requested value>", "match": "not_found"}}
{{"action": "update_focus", "value": "<requested value>", "match": "no_profiles"}}
{{"action": "reset_focus"}}
{{"action": "view_focus"}}
{{"action": "view_doc", "slug": "<slug>"}}
{{"action": "update_skill_param", "param": "<param_name>", "value": "<new_value>"}}
{{"action": "unknown", "message": "<why it's unclear>"}}"""

    try:
        raw    = ai.extract_json(prompt)
        parsed = json.loads(raw)
    except Exception:
        return (
            f"⚠️ Couldn't parse your instruction. Try:\n"
            f"  /context market_intel_focus equipment manufacturing\n"
            f"  /context writing_style make my tone more direct"
        )

    action = parsed.get("action", "unknown")

    if action == "update_focus":
        value = (parsed.get("value") or "").strip()
        if not value:
            return "⚠️ No industry specified. Example: /context market_intel_focus equipment manufacturing"

        match = parsed.get("match", "no_profiles")

        if match == "matched":
            canonical = (parsed.get("canonical") or value).strip()
            s_data["market_intel_focus"] = canonical
            _write_json(sett, s_data)
            return (
                f"✅ Market Intelligence focus updated: {canonical}\n\n"
                f"Takes effect on the next morning briefing run.\n"
                f"/context market_intel_focus reset to revert to all industries."
            )

        if match == "suggest":
            suggestions = parsed.get("suggestions") or []
            sugg_str    = "\n".join(f"  · {s}" for s in suggestions)
            return (
                f"⚠️ '{value}' doesn't exactly match any industry in your Company Profiles.\n\n"
                f"Did you mean one of these?\n{sugg_str}\n\n"
                f"Use /context market_intel_focus [industry] with the exact name to confirm."
            )

        if match == "not_found":
            available = _get_available_industries(sett)
            avail_str = "\n".join(f"  · {i}" for i in available) if available else "  (none — add companies first)"
            return (
                f"⚠️ '{value}' doesn't match any industry in your Company Profiles.\n\n"
                f"Available industries:\n{avail_str}\n\n"
                f"Use /context market_intel_focus [industry] with one of the above."
            )

        # match == "no_profiles" — no companies yet, accept as-is
        s_data["market_intel_focus"] = value
        _write_json(sett, s_data)
        return (
            f"✅ Market Intelligence focus set: {value}\n\n"
            f"Note: No Company Profiles found yet. Once you add companies, the focus will filter by this industry.\n"
            f"Takes effect on the next morning briefing run."
        )

    if action == "reset_focus":
        s_data["market_intel_focus"] = ""
        _write_json(sett, s_data)
        return "✅ Market Intelligence reset — next briefing will cover all industries from your Company Profiles."

    if action == "view_focus":
        focus = (s_data.get("market_intel_focus") or "").strip()
        return f"📰 Market Intelligence focus: {focus or 'all industries (default)'}"

    if action == "view_doc":
        slug = parsed.get("slug", "")
        if slug not in SLUGS:
            return f"Unknown document slug: {slug}"
        doc     = docs.get(slug, {})
        content = doc.get("content", "")
        title   = SLUGS[slug]
        if not content:
            return f"⬜ {title} — not set yet."
        updated = (doc.get("updated_at") or "")[:10]
        return f"{title} (updated {updated})\n\n{content[:1200]}{'…' if len(content) > 1200 else ''}"

    if action == "update_doc":
        slug        = parsed.get("slug", "")
        instruction = (parsed.get("instruction") or "").strip()
        if slug not in ALL_SLUGS:
            return f"Unknown document slug: {slug}"
        if not instruction:
            return f"No instruction provided for {ALL_SLUGS[slug]}."
        doc     = docs.get(slug, {})
        content = doc.get("content", "")
        title   = ALL_SLUGS[slug]
        if not content:
            return f"⬜ {title} has no content yet — generate it via the frontend first."
        if not ai or not ctx:
            return "⚠️ AI unavailable."
        from src.modules.context_docs import refine_document
        updated_content = refine_document(slug, content, instruction, ai)
        docs[slug] = {"slug": slug, "content": updated_content,
                      "updated_at": datetime.now(timezone.utc).isoformat()}
        ctx_data["documents"] = docs
        _write_json(ctx, ctx_data)
        if slug in ("business_profile", "writing_style") and sett:
            _sync_settings(slug, updated_content, sett)
        elif slug in SKILL_SLUGS and sett:
            from src.modules.context_docs import extract_settings_fields
            fields = extract_settings_fields({slug: updated_content})
            s_data = _read_json(sett)
            s_data.update(fields)
            _write_json(sett, s_data)
        preview = updated_content[:600] + ("…" if len(updated_content) > 600 else "")
        return f"✅ {title} updated.\n\nPreview:\n{preview}\n\nType /context {slug} to see the full document."

    if action == "update_skill_param":
        param = (parsed.get("param") or "").strip()
        value = (parsed.get("value") or "").strip()
        if not param or not value:
            return "⚠️ Couldn't identify which parameter to update. Try being more specific, e.g. 'change follow-up to 3 days'."
        return _update_skill_param(param, value, ctx, sett)

    # action == "unknown"
    msg = parsed.get("message", "")
    return (
        f"⚠️ {msg}\n\n"
        f"Try:\n"
        f"  /context market_intel_focus equipment manufacturing\n"
        f"  /context writing_style make my tone more direct\n"
        f"  /context business_profile add that we focus on SME clients"
    )


# ── /focus ────────────────────────────────────────────────────────────────────

def _focus(args: list, sett: "Path | None") -> str:
    s       = _read_json(sett)
    current = (s.get("market_intel_focus") or "").strip()

    if not args:
        if current:
            return (
                f"📰 Market Intelligence focus: {current}\n\n"
                f"Use /focus [industries] to change, or /focus reset to track all industries."
            )
        return (
            "📰 Market Intelligence focus: all industries (default)\n\n"
            "Use /focus [industries] to narrow, e.g.:\n"
            "  /focus equipment manufacturing, water utilities"
        )

    value = " ".join(args).strip()

    if value.lower() == "reset":
        s["market_intel_focus"] = ""
        _write_json(sett, s)
        return "✅ Market Intelligence reset — next briefing will cover all industries from your Company Profiles."

    s["market_intel_focus"] = value
    _write_json(sett, s)
    return (
        f"✅ Market Intelligence focus updated: {value}\n\n"
        f"Takes effect on the next morning briefing run.\n"
        f"Use /focus reset to revert to all industries."
    )


# ── Skill parameter update ────────────────────────────────────────────────────

_PARAM_MAP: dict[str, tuple] = {
    "reply_after_days":                 ("reply_needed_skill",       r'(##\s*Flag After\s*\nDays:\s*)\d+',                    "reply flag threshold",      "days", "int"),
    "reply_urgent_days":                ("reply_needed_skill",       r'(##\s*Urgent After\s*\nDays:\s*)\d+',                  "reply urgent threshold",    "days", "int"),
    "followup_after_days":              ("followup_needed_skill",    r'(##\s*Flag After\s*\nDays:\s*)\d+',                    "follow-up flag threshold",  "days", "int"),
    "followup_urgent_days":             ("followup_needed_skill",    r'(##\s*Urgent After\s*\nDays:\s*)\d+',                  "follow-up urgent threshold","days", "int"),
    "upcoming_commitments_days":        ("upcoming_commitments_skill",r'(Show commitments due within:\s*)\d+',                "commitments window",        "days", "int"),
    "upcoming_commitments_urgent_days": ("upcoming_commitments_skill",r'(Mark as urgent if due within:\s*)\d+',               "urgent commitments",        "days", "int"),
    "bi_lookback_days":                 ("business_insights_skill",  r'(Lookback window:\s*)\d+',                            "BI lookback window",        "days", "int"),
    "bi_top_contacts":                  ("relationship_health_skill", r'(Analyse top:\s*)\d+',                               "top contacts to analyse",   "contacts", "int"),
    "bi_active_days":                   ("relationship_health_skill", r'(Contacted within:\s*)\d+',                          "active relationship",        "days", "int"),
    "bi_atrisk_days":                   ("relationship_health_skill", r'(No contact in:\s*\d+\s*to\s*)\d+',                  "at-risk relationship",       "days", "int"),
    "briefing_style":                   ("morning_briefing_skill",   r'(Style:\s*)\S+',                                      "briefing style",             "",    "enum"),
}

_BRIEFING_STYLE_ALIASES = {
    "bullet": "bullets", "bullet-point": "bullets", "bullet point": "bullets", "bullets": "bullets",
    "detail": "detailed", "detailed": "detailed", "long": "detailed", "full": "detailed",
    "concise": "concise", "short": "concise", "brief": "concise",
}


def _update_skill_param(param: str, value: str,
                        ctx: "Path | None", sett: "Path | None") -> str:
    """Update a skill parameter in settings.json and sync the markdown in context.json."""
    if param not in _PARAM_MAP:
        valid = "\n  ".join(_PARAM_MAP.keys())
        return f"⚠️ Unknown parameter '{param}'. Valid parameters:\n  {valid}"

    skill_slug, pattern, label, unit, ptype = _PARAM_MAP[param]

    if ptype == "int":
        try:
            int_val = int(value)
            if int_val < 1:
                return f"⚠️ Value must be a positive integer."
            str_val = str(int_val)
        except ValueError:
            return f"⚠️ '{value}' is not a valid number for {label}."
    elif ptype == "enum":
        normalised = _BRIEFING_STYLE_ALIASES.get(value.lower().strip())
        if not normalised:
            return f"⚠️ Invalid style '{value}'. Valid options: concise · detailed · bullets"
        str_val = normalised
    else:
        str_val = value.strip()

    s_data = _read_json(sett)
    s_data[param] = int(str_val) if ptype == "int" else str_val
    if sett:
        _write_json(sett, s_data)

    if ctx and ctx.exists():
        try:
            ctx_data = _read_json(ctx)
            docs = ctx_data.get("documents", {})
            doc = docs.get(skill_slug, {})
            content = doc.get("content", "")
            if content:
                new_content = re.sub(pattern, rf'\g<1>{str_val}', content)
                if new_content != content:
                    docs[skill_slug] = {
                        "slug":       skill_slug,
                        "content":    new_content,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    ctx_data["documents"] = docs
                    _write_json(ctx, ctx_data)
        except Exception:
            pass

    unit_str = f" {unit}" if unit else ""
    return f"✅ {label.capitalize()} set to **{str_val}**{unit_str}. Takes effect on the next run."


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_json(path: "Path | None") -> dict:
    try:
        return json.loads(path.read_text()) if path and path.exists() else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    from src.storage import atomic_write_json
    atomic_write_json(path, data)


def _sync_settings(slug: str, content: str, sett: Path) -> None:
    from src.modules.context_docs import extract_settings_fields
    fields   = extract_settings_fields({slug: content})
    settings = _read_json(sett)
    settings.update(fields)
    _write_json(sett, settings)
