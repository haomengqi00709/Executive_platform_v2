"""
profile_init — AI-generated first-time profile drafts.

Runs after CRM and Projects scans complete. Produces three markdown drafts:
  - personal_profile.md  — single AI call (combined with market_segments)
  - market_segments.md   — same call as personal_profile
  - business_profile.md  — **two passes**:
      v1 from website data only (factual self-description, no inbox signals)
      v2 enriches v1 with real CRM client/partner/vendor names + project
         topics, producing the final 6-section document
    Only the final v2 fires on_doc_ready('business') so the user sees a
    single "Drafting your business profile" reveal — the v1 write is
    silent. See repo CLAUDE.md for the data-flow rationale.

Section headers in business_profile.md mirror what the original v1 wizard
produced for Daniel (i3d) — keep those header strings stable so existing
profile-readers downstream don't have to special-case the new layout.
"""
import json
import re
from collections import Counter
from html import unescape
from pathlib import Path

from src.ai import AIClient
from src.graph import GraphClient
from src.modules.profile import (
    save_business_profile,
    save_market_segments,
    save_personal_profile,
)

_SIGNATURE_SAMPLES = 8   # how many recent sent emails to look at
_MAX_BODY_CHARS = 3000   # truncate each body so the prompt stays reasonable

# CRM contact statuses we surface in business_profile v2. Order matters — it's
# the section order inside the prompt. "internal" is excluded (team size signal
# is interesting but doesn't belong in a public-facing profile section).
_CRM_STATUSES_FOR_BUSINESS = ("client", "prospect", "partner", "investor", "vendor")


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _collect_signatures(graph: GraphClient, log) -> list[str]:
    """Pull recent sent emails, return the trailing ~600 chars of each body (where signatures live)."""
    try:
        raw = graph.get_messages(
            top=_SIGNATURE_SAMPLES,
            folder="SentItems",
            orderby="sentDateTime desc",
        )
    except Exception as e:
        log(f"sent-email fetch failed: {e}")
        return []

    samples = []
    for msg in raw:
        body = msg.get("body") or {}
        content = body.get("content") or ""
        if body.get("contentType", "").lower() == "html":
            content = _strip_html(content)
        content = content[:_MAX_BODY_CHARS].strip()
        if content:
            samples.append(content[-600:])
    return samples


def _collect_crm_titles(data_dir: Path) -> list[tuple[str, int]]:
    crm_path = Path(data_dir) / "crm.json"
    if not crm_path.exists():
        return []
    try:
        crm = json.loads(crm_path.read_text())
    except Exception:
        return []

    titles = Counter()
    for c in crm.get("contacts", {}).values():
        if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore":
            continue
        if c.get("status") not in ("client", "prospect", "partner", "investor"):
            continue
        role = (c.get("role") or "").strip()
        if role:
            titles[role] += 1
    return titles.most_common(15)


def _collect_crm_companies_by_status(data_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """For business_profile v2: group active contacts by status, count distinct
    companies per status, and rank by contact count (most-engaged company first).

    Returns e.g. {
      "client":   [("ExxonMobil", 4), ("Fertiglobe", 3), ...],
      "prospect": [...],
      "partner":  [...],
      ...
    }
    """
    crm_path = Path(data_dir) / "crm.json"
    if not crm_path.exists():
        return {}
    try:
        crm = json.loads(crm_path.read_text())
    except Exception:
        return {}

    buckets: dict[str, Counter] = {s: Counter() for s in _CRM_STATUSES_FOR_BUSINESS}
    for c in crm.get("contacts", {}).values():
        if c.get("ignore") or c.get("archived") or c.get("priority") == "ignore":
            continue
        status = c.get("status")
        if status not in buckets:
            continue
        company = (c.get("company") or "").strip()
        if company:
            buckets[status][company] += 1

    return {status: counter.most_common(10) for status, counter in buckets.items() if counter}


def _collect_working_hours(graph: GraphClient, log) -> dict:
    """Analyse when the user actually sends emails. Returns a dict with the
    user's primary send-window (UTC), weekend ratio, and late-night ratio —
    so the personal_profile "Working hours preference" section can be filled
    from real behavior instead of "(Confirm with user)".

    Times are kept in UTC. The downstream prompt notes this so the AI doesn't
    pretend it knows the user's timezone — if the user wants local hours, they
    can edit later. Pulls a larger sample (100 emails) than _collect_signatures
    because hour distribution needs more data points to be meaningful.
    """
    from datetime import datetime
    try:
        raw = graph.get_messages(
            top=100,
            folder="SentItems",
            orderby="sentDateTime desc",
        )
    except Exception as e:
        log(f"working-hours fetch failed: {e}")
        return {}

    hours: list[int] = []
    weekend = 0
    weekday = 0
    for msg in raw:
        ts = msg.get("sentDateTime") or ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        hours.append(dt.hour)
        if dt.weekday() >= 5:
            weekend += 1
        else:
            weekday += 1

    if len(hours) < 5:
        return {}

    hours_sorted = sorted(hours)
    n = len(hours_sorted)
    # 10th–90th percentile window — discards outliers without losing the bulk
    p10 = hours_sorted[max(0, n // 10)]
    p90 = hours_sorted[min(n - 1, (9 * n) // 10)]
    total = weekday + weekend
    weekend_pct = round(weekend * 100 / total) if total else 0
    late_night = sum(1 for h in hours if h >= 22 or h < 4)
    late_pct = round(late_night * 100 / total) if total else 0
    return {
        "sample_size":          n,
        "primary_window_utc":   f"{p10:02d}:00–{p90:02d}:00 UTC",
        "weekend_ratio_pct":    weekend_pct,
        "late_night_ratio_pct": late_pct,
    }


def _detect_languages(signatures: list[str]) -> list[str]:
    """Heuristic language detection from sent-email body samples. Returns a
    list of language names. Conservative — only reports a language when
    there's clear evidence (a few signal words or enough characters).
    """
    if not signatures:
        return []
    blob = " ".join(signatures)
    detected: list[str] = []

    cjk_chars = re.findall(r"[一-鿿]", blob)
    if len(cjk_chars) > 20:
        detected.append("Chinese")
    elif len(cjk_chars) > 5:
        detected.append("Chinese (occasional)")

    latin_words = re.findall(r"\b[a-zA-Z]{3,}\b", blob)
    if len(latin_words) > 30:
        lc = [w.lower() for w in latin_words]
        en_signals = sum(1 for w in lc if w in {
            "the", "and", "that", "with", "this", "for", "from", "have",
            "thanks", "regards", "hi", "hello", "best", "sincerely",
        })
        fr_signals = sum(1 for w in lc if w in {
            "merci", "cordialement", "bonjour", "bonsoir", "salut",
            "monsieur", "madame", "votre", "cher", "chère",
        })
        es_signals = sum(1 for w in lc if w in {
            "gracias", "saludos", "hola", "buenos", "buenas", "señor",
            "señora", "estimado", "estimada",
        })
        if en_signals >= 5:
            detected.append("English")
        if fr_signals >= 3:
            detected.append("French")
        if es_signals >= 3:
            detected.append("Spanish")

    return detected


def _collect_project_topics(data_dir: Path) -> list[tuple[str, int]]:
    proj_path = Path(data_dir) / "projects.json"
    if not proj_path.exists():
        return []
    try:
        projs = json.loads(proj_path.read_text())
    except Exception:
        return []

    topics = Counter()
    for p in projs.get("projects", {}).values():
        if p.get("ignore") or p.get("archived"):
            continue
        for t in p.get("key_topics", []) or []:
            t = (t or "").strip()
            if t:
                topics[t] += 1
    return topics.most_common(20)


# ─── personal_profile + market_segments (single AI call) ──────────────────


def _build_personal_segments_prompt(
    display_name: str,
    user_email: str,
    signatures: list[str],
    crm_titles: list[tuple[str, int]],
    project_topics: list[tuple[str, int]],
    company_name: str,
    company_market_segments: list[str],
    linkedin_bio: str,
    working_hours: dict,
    languages: list[str],
) -> str:
    sig_block = "\n---\n".join(signatures) if signatures else "(no signature samples found)"
    titles_block = "\n".join(f"- {t} ({n})" for t, n in crm_titles) or "(no CRM titles yet)"
    topics_block = "\n".join(f"- {t} ({n})" for t, n in project_topics) or "(no project topics yet)"

    if working_hours:
        wh_block = (
            f"- Primary send window: {working_hours.get('primary_window_utc', 'n/a')}\n"
            f"- Weekend sends: {working_hours.get('weekend_ratio_pct', 0)}% of total\n"
            f"- Late-night sends (22:00–04:00 UTC): {working_hours.get('late_night_ratio_pct', 0)}%\n"
            f"- Sample size: {working_hours.get('sample_size', 0)} recent sent emails"
        )
    else:
        wh_block = "(no send-time data — insufficient sent emails)"

    if languages:
        lang_block = ", ".join(languages)
    else:
        lang_block = "(could not detect from signatures)"

    user_provided_block = ""
    if linkedin_bio or company_market_segments or company_name:
        parts = ["## USER-PROVIDED CONTEXT (highest priority — trust this over the inferred data below)"]
        if company_name:
            parts.append(f"Company: {company_name}")
        if linkedin_bio:
            parts.append(f"Personal bio (pasted by {display_name}):\n{linkedin_bio}")
        if company_market_segments:
            parts.append("Market segments (from website):")
            for s in company_market_segments:
                parts.append(f"  - {s}")
        user_provided_block = "\n".join(parts) + "\n\n---\n\n"

    return f"""You are drafting the personal_profile.md and market_segments.md drafts
for {display_name} (email: {user_email}). These are the long-lived context
layer the AI reads on every feature — keep them tight and concrete.

{user_provided_block}Below is everything else we know from analysing the mailbox.

## Signature samples (last {_SIGNATURE_SAMPLES} sent emails — look at the tail of each)
{sig_block}

## Top contact titles from CRM
{titles_block}

## Recurring topics across active projects
{topics_block}

## Working-time pattern (computed from 100 most recent sent emails)
{wh_block}

## Languages detected in sent emails
{lang_block}

---

Produce TWO markdown drafts.

### 1. personal_profile.md
Sections (use these exact H2 headers):
- Name and title
- Company
- Contact
- Languages
- Working hours preference
- Other preferences AI should know

Filling rules:
- "Name and title" — pull title from email signatures if present (CEO, VP X,
  Director Y, etc.); leave bare name + `- (Confirm with user)` ONLY if no
  signature gave a title.
- "Languages" — use the "Languages detected" data above verbatim. Only write
  `- (Confirm with user)` if detection returned nothing.
- "Working hours preference" — quote the primary send window above and add
  one short qualifier (e.g. "occasional weekend work" if weekend ratio > 15%,
  "occasional late nights" if late-night ratio > 10%). Note times are UTC.
  Only fall back to `- (Confirm with user)` if no send-time data was available.
- Other sections — infer tightly from signatures + LinkedIn bio. 1-3 lines.

### 2. market_segments.md
Sections (use these exact H2 headers):
- Primary segments
- Secondary / adjacent segments
- Geographic markets
- Segments to ignore

If the user-provided market segments list is non-empty, those ARE the Primary
segments — promote them verbatim. Otherwise infer from project topics + CRM.

Rules:
- Lead each H2 with a concrete answer. Do not hedge.
- When data does not support a confident answer, write a single bullet:
  `- (Confirm with user)` so they know to fill it in.
- Keep each section to 2-4 bullets or 1-3 sentences. The user will edit, write tight.
- Do not invent specific revenue, headcount, or client names not present in the data.
- Plain English, not telegraphic notes.

Return a JSON object with two string keys:
{{
  "personal_profile": "# Personal Profile\\n\\n## Name and title\\n...",
  "market_segments":  "# Market Segments\\n\\n## Primary segments\\n..."
}}
"""


# ─── business_profile v1 (website data only) ──────────────────────────────


def _user_title_from_signatures(signatures: list[str]) -> str:
    """Best-effort: pull the user's role/title line out of the most recent
    signature. Looks for short lines following their name. Empty if nothing
    obvious — caller falls back to a generic header.
    """
    if not signatures:
        return ""
    # Last signature is the most recent. Take the last ~12 non-empty lines.
    tail = [ln.strip() for ln in signatures[0].split(".") if ln.strip()]
    for line in tail[:6]:
        # Common patterns: "CEO", "Founder & CEO", "VP Engineering"
        m = re.search(r"\b(CEO|CTO|CFO|COO|Founder|Co-Founder|President|VP|Director|Head of [A-Z][a-z]+)\b[^.]*", line)
        if m:
            return m.group(0).strip()
    return ""


def _build_business_v1_prompt(
    display_name: str,
    user_email: str,
    user_title: str,
    company_name: str,
    company_headquarters: str,
    company_what_they_do: str,
    company_business_lines: list[str],
    company_products: list[str],
    company_segments: list[str],
    company_role_emails: list[str],
    website_url: str,
) -> str:
    def _bullets(items: list[str]) -> str:
        return "\n".join(f"  - {s}" for s in items) if items else "  (none provided)"

    title_line = f"**{display_name}**" + (f", {user_title}" if user_title else "")
    company_line = f" at {company_name}" if company_name else ""

    return f"""You are writing the FIRST PASS of business_profile.md for {display_name}.

This pass uses ONLY data the user gave us from their company website — the
official, factual self-description. Inbox-derived data (real clients,
strategic focus from email patterns) is NOT yet available; a second pass
will enrich this draft after the CRM and projects scans complete.

## Website-derived facts (use ONLY these — do not invent anything else)
Company name:            {company_name or "(unknown)"}
Headquarters:            {company_headquarters or "(unknown)"}
What they do:            {company_what_they_do or "(not stated on site)"}
Business lines:
{_bullets(company_business_lines)}
Named products / services:
{_bullets(company_products)}
Industries (segments):
{_bullets(company_segments)}
Functional contact emails:
{_bullets(company_role_emails)}
Source URL:              {website_url or "(not provided)"}

---

Produce business_profile.md with EXACTLY this structure (these H2 headers,
this order, this top-line attribution). Where website data is missing,
write the placeholder bullet `- (pending — enriching from your inbox)`
verbatim so the second pass knows what to fill.

```
# Business Profile

> Profile for {title_line}{company_line}

## What the company does
- (bullet from `what they do` — quote the website's phrasing if concise)
- (one bullet per business line, from `business lines`)
- (one bullet for products if listed: e.g. "Products: X, Y, Z")

## Scale and stage
- (one bullet stating headquarters if known)
- (pending — enriching from your inbox)

## Typical customers
- (pending — enriching from your inbox)

## Current strategic focus
- (pending — enriching from your inbox)

## Competitors and adjacent players
- (Confirm with user)

## Reference contacts
- (one bullet per role email, formatted as `email@x.com — purpose`,
   e.g. "info@x.com — general inbox", "sales@x.com — sales inquiries".
   Omit this section entirely if no role emails were provided.)
```

Rules:
- Keep "What the company does" bullets short (1 line each). Use the
  website's wording where you can — don't paraphrase if their phrasing
  works.
- "Scale and stage" v1 only states HQ; the rest is a single placeholder
  bullet the second pass will replace.
- If `what they do` is "(not stated on site)" AND `business lines` is
  empty AND `products` is empty, write a single placeholder bullet under
  "What the company does": `- (pending — enriching from your inbox)`.
- Do NOT invent founding year, employee count, revenue, or named
  customers — none of those are in the website-derived data above.
- Do NOT add sections that aren't in the template.

Return a JSON object with one string key:
{{ "business_profile": "# Business Profile\\n\\n> Profile for ..." }}
"""


# ─── business_profile v2 (CRM-enriched) ───────────────────────────────────


def _build_business_v2_prompt(
    v1_markdown: str,
    crm_companies: dict[str, list[tuple[str, int]]],
    crm_titles: list[tuple[str, int]],
    project_topics: list[tuple[str, int]],
) -> str:
    def _company_lines(status: str) -> str:
        entries = crm_companies.get(status, [])
        if not entries:
            return "  (none in CRM)"
        return "\n".join(f"  - {company} ({n} contact{'s' if n != 1 else ''})"
                         for company, n in entries)

    titles_block = "\n".join(f"- {t} ({n})" for t, n in crm_titles[:10]) or "(none)"
    topics_block = "\n".join(f"- {t} ({n})" for t, n in project_topics[:15]) or "(none)"

    return f"""You are running the SECOND PASS of business_profile.md. The first
pass produced the document below from website data only — left placeholder
bullets `- (pending — enriching from your inbox)` in sections that need
inbox-derived data.

Your job: take that v1 document, fill in the placeholder sections with the
CRM and project data below, and return the complete updated document.

## v1 (website-only) document
```
{v1_markdown}
```

## CRM contacts grouped by status (most-engaged company first per group)
### Clients
{_company_lines("client")}
### Prospects
{_company_lines("prospect")}
### Partners
{_company_lines("partner")}
### Investors
{_company_lines("investor")}
### Vendors
{_company_lines("vendor")}

## Decision-maker titles met (across all active contacts)
{titles_block}

## Recurring topics across active projects (12mo window)
{topics_block}

---

Update the document section by section. ONLY rewrite these:

**§ Scale and stage** — keep the website HQ bullet exactly as v1 wrote it.
Replace the `(pending — enriching from your inbox)` bullet with bullets
that summarize: notable enterprise clients by name (pick 2-4 from the
Clients list above — these are the most-engaged), and any signal about
international vs domestic scope from the project topics. Keep tight,
2-3 bullets max.

**§ Typical customers** — replace the placeholder with bullets describing:
the kinds of organizations the user actually works with (infer from
client + prospect company names and the decision-maker titles), and the
roles they typically engage. 2-4 bullets.

**§ Current strategic focus** — replace the placeholder with bullets
inferred from project topics. What themes recur? Are they expanding,
defending, partnering, executing? 2-4 bullets.

DO NOT touch these sections — copy them verbatim from v1:
- The top attribution line (`> Profile for ...`)
- `## What the company does`
- `## Competitors and adjacent players`
- `## Reference contacts`

Rules:
- Never invent client names — only use companies from the CRM lists above.
- If a CRM bucket is empty, leave that aspect out of the v2 narrative
  rather than fabricating one.
- Keep each section to 2-4 bullets. The user will edit; write tight.
- Plain English, not telegraphic notes.
- If you genuinely cannot improve a section beyond v1, leave its v1 bullets
  as-is (don't overwrite a real bullet with `(Confirm with user)`).

Return a JSON object with one string key, containing the COMPLETE updated
markdown document:
{{ "business_profile": "# Business Profile\\n\\n> Profile for ..." }}
"""


# ─── orchestration ────────────────────────────────────────────────────────


def run_profile_init(
    data_dir: Path,
    graph: GraphClient,
    ai: AIClient,
    settings: dict,
    progress=None,
    on_doc_ready=None,
) -> dict:
    """
    Generates personal_profile.md, market_segments.md and business_profile.md
    drafts. Writes to disk. Status management is the caller's responsibility —
    this function does NOT modify init_status.json.

    Phases (all internal to this function):
      1. business_v1   — website-only draft, written silently
      2. personal + segments  — single combined AI call
      3. business_v2   — re-reads CRM + project data, rewrites business_profile

    on_doc_ready(doc_key, content): fired once per doc, in this order:
      - "personal"  after phase 2
      - "segments"  after phase 2
      - "business"  after phase 3
    The v1 write is INTENTIONALLY silent so the onboarding reveal page shows
    a single "Drafting your business profile" card flipping ✓ at the end of
    phase 3, not flickering mid-process.

    Settings inputs (populated by the onboarding wizard's Steps 1–3):
      display_name, report_email, linkedin_bio,
      company_name, company_website_url, company_headquarters,
      company_what_they_do, company_business_lines, company_products,
      company_market_segments, company_role_emails

    Returns final {personal_profile, business_profile, market_segments}.
    """
    data_dir = Path(data_dir)

    def log(msg: str):
        if progress:
            progress(msg)
        print(f"[profile_init] {msg}")

    log("Starting profile generation...")

    display_name = settings.get("display_name") or "the executive"
    user_email   = settings.get("report_email") or settings.get("username") or ""
    linkedin_bio = (settings.get("linkedin_bio") or "").strip()
    company_name            = (settings.get("company_name") or "").strip()
    company_website_url     = (settings.get("company_website_url") or "").strip()
    company_headquarters    = (settings.get("company_headquarters") or "").strip()
    company_what_they_do    = (settings.get("company_what_they_do")
                               or settings.get("company_description") or "").strip()
    company_business_lines  = settings.get("company_business_lines") or []
    company_products        = settings.get("company_products") or []
    company_segments        = settings.get("company_market_segments") or []
    company_role_emails     = settings.get("company_role_emails") or []
    for var in (company_business_lines, company_products, company_segments, company_role_emails):
        if not isinstance(var, list):
            var.clear() if hasattr(var, "clear") else None  # defensive

    # Collect inbox-derived signals once — used by phases 2 and 3.
    signatures     = _collect_signatures(graph, log)
    crm_titles     = _collect_crm_titles(data_dir)
    project_topics = _collect_project_topics(data_dir)
    crm_companies  = _collect_crm_companies_by_status(data_dir)
    working_hours  = _collect_working_hours(graph, log)
    languages      = _detect_languages(signatures)
    log(f"Collected {len(signatures)} signatures, {len(crm_titles)} CRM titles, "
        f"{len(project_topics)} project topics, "
        f"{sum(len(v) for v in crm_companies.values())} CRM companies across "
        f"{len([k for k, v in crm_companies.items() if v])} statuses, "
        f"working_hours={'yes' if working_hours else 'insufficient data'}, "
        f"languages={languages or 'undetected'}")

    user_title = _user_title_from_signatures(signatures)

    # ─── Phase 1: business_profile v1 (silent) ────────────────────────────
    log("Phase 1: business_profile v1 (website-only)...")
    v1_md = ""
    try:
        v1_raw = ai.extract_json(_build_business_v1_prompt(
            display_name=display_name,
            user_email=user_email,
            user_title=user_title,
            company_name=company_name,
            company_headquarters=company_headquarters,
            company_what_they_do=company_what_they_do,
            company_business_lines=company_business_lines,
            company_products=company_products,
            company_segments=company_segments,
            company_role_emails=company_role_emails,
            website_url=company_website_url,
        ))
        v1_data = json.loads(v1_raw)
        v1_md = (v1_data.get("business_profile") or "").strip()
        if v1_md:
            save_business_profile(data_dir, v1_md)
            log(f"v1 written silently ({len(v1_md)} chars)")
        else:
            log("v1 came back empty — phase 2 will skip enrichment")
    except Exception as e:
        log(f"v1 generation failed: {e}; continuing to phases 2/3")

    # ─── Phase 2: personal + market_segments (single AI call) ─────────────
    log("Phase 2: personal_profile + market_segments...")
    personal, segments = "", ""
    try:
        ps_raw = ai.extract_json(_build_personal_segments_prompt(
            display_name=display_name,
            user_email=user_email,
            signatures=signatures,
            crm_titles=crm_titles,
            project_topics=project_topics,
            company_name=company_name,
            company_market_segments=company_segments,
            linkedin_bio=linkedin_bio,
            working_hours=working_hours,
            languages=languages,
        ))
        ps_data = json.loads(ps_raw)
        personal = (ps_data.get("personal_profile") or "").strip()
        segments = (ps_data.get("market_segments")  or "").strip()
    except Exception as e:
        log(f"Phase 2 failed ({e}); personal + segments left blank")

    if personal:
        save_personal_profile(data_dir, personal)
        log(f"Wrote personal_profile.md ({len(personal)} chars)")
        if on_doc_ready:
            on_doc_ready("personal", personal)
    if segments:
        save_market_segments(data_dir, segments)
        log(f"Wrote market_segments.md ({len(segments)} chars)")
        if on_doc_ready:
            on_doc_ready("segments", segments)

    # ─── Phase 3: business_profile v2 (CRM-enriched, overwrites v1) ───────
    log("Phase 3: business_profile v2 (CRM enrichment)...")
    business_final = v1_md  # fallback: if v2 fails, the file stays as v1
    if v1_md:
        try:
            v2_raw = ai.extract_json(_build_business_v2_prompt(
                v1_markdown=v1_md,
                crm_companies=crm_companies,
                crm_titles=crm_titles,
                project_topics=project_topics,
            ))
            v2_data = json.loads(v2_raw)
            v2_md = (v2_data.get("business_profile") or "").strip()
            if v2_md:
                save_business_profile(data_dir, v2_md)
                log(f"Wrote business_profile.md v2 ({len(v2_md)} chars)")
                business_final = v2_md
        except Exception as e:
            log(f"v2 enrichment failed ({e}); leaving v1 on disk")

    if business_final and on_doc_ready:
        on_doc_ready("business", business_final)

    log("Done")
    return {
        "personal_profile": personal,
        "business_profile": business_final,
        "market_segments":  segments,
    }
