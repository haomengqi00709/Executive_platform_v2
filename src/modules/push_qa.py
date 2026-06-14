"""
Push-quality spot-check (ops stream 4) — an OBSERVER layer, separate from the
inline validator (src/modules/validator.py).

The validator runs INSIDE each section's generation and filters individual items
before they're shown. push_qa runs AFTER the fact: it samples already-produced
section results across the fleet and asks "is this push the answer we'd expect?",
surfacing quality regressions to the OPERATOR, not the customer. Crucially it can
catch failures the validator structurally cannot — e.g. a fabricated list where
the source never reached the generator (each item looks individually plausible,
so the inline validator keeps them).

Three independent checks per sampled section:
  1. heuristics — pure rules, no AI: count anomaly vs the section's own recent
     baseline, all-same-priority, required fields missing, empty-when-baseline-
     was-not.
  2. grounding  — anti-hallucination: for sections that make factual claims,
     fetch the claimed source email by id and ask the judge whether the item is
     actually derivable from it.
  3. judge      — an independent Gemini scores the push 1-5 on relevance /
     accuracy / tone / completeness, with a reason.

Verdict per section: ok | warn | fail (worst of the three). Fail-safe
everywhere: any check that errors degrades to "skipped", never raises.

Cost: makes Gemini calls. The caller (scheduler job) is gated behind
PUSH_QA_ENABLED so this never runs unless explicitly turned on.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Sections worth QA'ing first: they push to Teams and make factual claims.
DEFAULT_SECTIONS = ["reply_needed", "followup_needed", "commitments_extract", "ai_summary"]

# Required fields per section — a missing one means a malformed push.
_REQUIRED_FIELDS = {
    "reply_needed":        ["subject", "from_email", "reason", "priority"],
    "followup_needed":     ["subject", "reason"],
    "commitments_extract": ["description"],
}

# Sections whose items carry an `email_id` we can fetch for grounding.
_GROUNDABLE = {"reply_needed", "followup_needed", "commitments_extract"}

_GROUND_SAMPLE = 2          # how many items per section to ground-check
_BASELINE_RUNS = 5         # rolling window for the count baseline


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default


def _result_path(data_dir: Path, section_id: str) -> Path:
    return data_dir / "results" / f"{section_id}.json"


# ── 1. Heuristics (no AI) ─────────────────────────────────

def _heuristics(section_id: str, env: dict, baseline_counts: list) -> list:
    flags = []
    items = env.get("items") or []
    count = env.get("count", len(items))

    avg = (sum(baseline_counts) / len(baseline_counts)) if baseline_counts else None
    if avg is not None and avg >= 3:
        if count == 0:
            flags.append(f"empty_now (baseline avg {avg:.1f})")
        elif count < avg * 0.3:
            flags.append(f"count_drop ({count} vs avg {avg:.1f})")
        elif count > avg * 3:
            flags.append(f"count_spike ({count} vs avg {avg:.1f})")

    priorities = [it.get("priority") for it in items if it.get("priority")]
    if len(items) > 3 and len(set(priorities)) == 1 and priorities:
        flags.append(f"all_same_priority ({priorities[0]})")

    required = _REQUIRED_FIELDS.get(section_id)
    if required:
        for i, it in enumerate(items):
            missing = [f for f in required if not it.get(f)]
            if missing:
                flags.append(f"item[{i}] missing {missing}")
                break  # one example is enough

    return flags


# ── 2. Grounding (anti-hallucination, AI + Graph) ─────────

def _grounding_check(section_id: str, items: list, ai, graph) -> dict:
    """Fetch the cited source email for a few items and ask whether each item is
    actually derivable from it. Returns {checked, ungrounded:[...], uncertain:[...]}."""
    out = {"checked": 0, "ungrounded": [], "uncertain": []}
    if section_id not in _GROUNDABLE or graph is None:
        return out

    sampled = [it for it in items if it.get("email_id")][:_GROUND_SAMPLE]
    for it in sampled:
        try:
            msg = graph.get_message(it["email_id"])
        except Exception:
            continue  # source unreachable — can't ground, don't penalize
        src_subject = (msg.get("subject") or "")[:200]
        src_from = ((msg.get("from") or {}).get("emailAddress") or {}).get("address", "")
        src_body = (msg.get("bodyPreview")
                    or ((msg.get("body") or {}).get("content") or ""))[:1500]
        claim = json.dumps({k: it.get(k) for k in
                            ("subject", "from_email", "reason", "description") if it.get(k)},
                           ensure_ascii=False)
        prompt = f"""You are auditing one item from an executive assistant's "{section_id}" push for hallucination.

THE ITEM THE ASSISTANT PRODUCED:
{claim}

THE ACTUAL SOURCE EMAIL IT CLAIMS TO BE ABOUT:
Subject: {src_subject}
From: {src_from}
Body: {src_body}

Is the item genuinely derivable from this source email — same sender/subject/topic,
and any stated reason actually supported by the body? Answer strictly:
{{"grounded": "yes" | "no" | "uncertain", "why": "<short>"}}"""
        try:
            raw = ai.extract_json(prompt)
            verdict = json.loads(raw) if isinstance(raw, str) else raw
            out["checked"] += 1
            g = (verdict or {}).get("grounded", "uncertain")
            label = {"subject": it.get("subject") or it.get("description", ""),
                     "why": (verdict or {}).get("why", "")}
            if g == "no":
                out["ungrounded"].append(label)
            elif g == "uncertain":
                out["uncertain"].append(label)
        except Exception:
            continue
    return out


# ── 3. LLM judge (holistic score) ─────────────────────────

def _compact(section_id: str, env: dict) -> str:
    if section_id == "ai_summary":
        return "BRIEFING TEXT:\n" + (env.get("briefing") or "(empty)")[:2500]
    items = env.get("items") or []
    lines = [f"{len(items)} item(s):"]
    for i, it in enumerate(items[:20], 1):
        label = (it.get("subject") or it.get("description") or it.get("headline")
                 or it.get("name") or json.dumps(it, ensure_ascii=False)[:120])
        pri = it.get("priority", "")
        reason = (it.get("reason") or "")[:120]
        lines.append(f"[{i}] {label}" + (f" | {pri}" if pri else "") + (f" | {reason}" if reason else ""))
    return "\n".join(lines)


def _judge(section_id: str, env: dict, ai, display_name: str) -> dict:
    """Independent 1-5 score on relevance/accuracy/tone/completeness."""
    compact = _compact(section_id, env)
    prompt = f"""You are a quality auditor for {display_name}'s executive assistant.
Below is one "{section_id}" output that was pushed to the executive. Score it as a
reviewer who knows what a good version looks like. Do NOT rewrite it — judge it.

OUTPUT UNDER REVIEW:
{compact}

Score 1-5 (5=excellent, 1=unusable) on each dimension and give one overall score
(the minimum a busy executive would tolerate). Return strictly:
{{"overall": <1-5>, "relevance": <1-5>, "accuracy": <1-5>, "tone": <1-5>,
  "completeness": <1-5>, "reason": "<one sentence>"}}"""
    raw = ai.extract_json(prompt)
    verdict = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(verdict, dict):
        raise ValueError("judge returned non-object")
    return verdict


# ── Orchestration ─────────────────────────────────────────

def _verdict(heuristic_flags: list, grounding: dict, judge: dict | None) -> str:
    if grounding.get("ungrounded"):
        return "fail"
    score = (judge or {}).get("overall")
    if isinstance(score, (int, float)) and score <= 2:
        return "fail"
    if heuristic_flags or grounding.get("uncertain") or (isinstance(score, (int, float)) and score == 3):
        return "warn"
    return "ok"


def evaluate_section(data_dir: Path, section_id: str, ai, graph, display_name: str,
                     baseline_counts: list, sampled: bool = True) -> dict:
    env = _read_json(_result_path(data_dir, section_id), None)
    if not env:
        return {"section_id": section_id, "verdict": "skipped", "reason": "no result file"}

    items = env.get("items") or []
    result = {
        "section_id":  section_id,
        "evaluated_at": _now_iso(),
        "last_run":    env.get("last_run"),
        "status":      env.get("status"),
        "count":       env.get("count", len(items)),
    }

    flags = _heuristics(section_id, env, baseline_counts)
    result["heuristic_flags"] = flags

    # The AI checks (grounding + judge) cost Gemini quota. Run them only when the
    # section looks suspicious (heuristics flagged it) OR it's this run's rotating
    # sample — so cost scales with problems found, not users × sections.
    do_ai = bool(flags) or sampled
    if do_ai:
        try:
            result["grounding"] = _grounding_check(section_id, items, ai, graph)
        except Exception as e:
            result["grounding"] = {"checked": 0, "ungrounded": [], "uncertain": [], "error": str(e)[:200]}
        judge = None
        if section_id == "ai_summary" or items:
            try:
                judge = _judge(section_id, env, ai, display_name)
            except Exception as e:
                result["judge_error"] = str(e)[:200]
        result["judge"] = judge
        result["ai_checked"] = True
        result["verdict"] = _verdict(flags, result["grounding"], judge)
    else:
        result["grounding"] = {"checked": 0, "ungrounded": [], "uncertain": []}
        result["judge"] = None
        result["ai_checked"] = False
        result["verdict"] = "ok"   # heuristics passed; not deep-checked this round
    return result


def run_for_user(data_dir: Path, ai, graph, display_name: str = "the executive",
                 sections: list | None = None) -> dict:
    """Evaluate the configured sections for one user. Writes .push_qa.json and
    returns a compact per-user summary for the fleet roll-up. Never raises."""
    sections = sections or _env_sections()
    hist_path = data_dir / ".push_qa_history.json"
    history = _read_json(hist_path, {}) or {}

    # Rotating AI sample: deep-check only N sections per run (default 1), cycling
    # through the list, so clean sections still get spot-checked over time without
    # paying for every section every run. Suspicious sections are always AI-checked
    # regardless (see evaluate_section). Set PUSH_QA_SAMPLE_PER_RUN=0 to disable.
    sample_n = max(0, int(os.getenv("PUSH_QA_SAMPLE_PER_RUN", "1")))
    cursor = history.get("_cursor") if isinstance(history.get("_cursor"), int) else 0
    sampled_ids = set()
    if sample_n and sections:
        for i in range(min(sample_n, len(sections))):
            sampled_ids.add(sections[(cursor + i) % len(sections)])
        history["_cursor"] = (cursor + sample_n) % len(sections)

    evaluations = []
    for sid in sections:
        baseline = (history.get(sid) or {}).get("counts", []) if isinstance(history.get(sid), dict) else []
        try:
            ev = evaluate_section(data_dir, sid, ai, graph, display_name, baseline,
                                  sampled=(sid in sampled_ids))
        except Exception as e:
            ev = {"section_id": sid, "verdict": "skipped", "reason": f"error: {e!s}"[:200]}
        evaluations.append(ev)

        # Update rolling baseline only from real runs.
        if ev.get("count") is not None and ev.get("verdict") != "skipped":
            counts = (history.get(sid) or {}).get("counts", [])
            counts = (counts + [ev["count"]])[-_BASELINE_RUNS:]
            history[sid] = {"counts": counts}

    summary = {
        "evaluated_at": _now_iso(),
        "sections":     evaluations,
        "fail":         sum(1 for e in evaluations if e.get("verdict") == "fail"),
        "warn":         sum(1 for e in evaluations if e.get("verdict") == "warn"),
        "ok":           sum(1 for e in evaluations if e.get("verdict") == "ok"),
    }
    _write_json(data_dir / ".push_qa.json", summary)
    _write_json(hist_path, history)
    return summary


def _env_sections() -> list:
    raw = (os.getenv("PUSH_QA_SECTIONS") or "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return list(DEFAULT_SECTIONS)


def _write_json(p: Path, data) -> None:
    try:
        from src.storage import atomic_write_json
        atomic_write_json(p, data)
    except Exception:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            tmp.replace(p)
        except Exception:
            pass
