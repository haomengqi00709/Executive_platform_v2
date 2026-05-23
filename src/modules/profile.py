"""
profile module — user's static company profile.

Two files per user, written once and rarely changed:
  .data/{user_id}/profile/business_profile.md — what the user's company does
  .data/{user_id}/profile/market_segments.md  — which markets they serve

The combined text is injected into AI prompts so search results,
email priority decisions, and summaries are tailored to the user's business.

A small status file (init_status.json) tracks the onboarding lifecycle so the
frontend knows whether to route the user to the Onboarding page or Dashboard.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

_PROFILE_SUBDIR = "profile"

_DEFAULT_BUSINESS_PROFILE = """\
# Business Profile

> Describe your company in 4-8 short paragraphs. The AI reads this every time
> it searches, summarises, or scores emails — so be specific and concrete.

## What the company does
(One short paragraph: products, services, value proposition.)

## Scale and stage
(Headcount, revenue range, geography, founded year — keep it factual.)

## Typical customers
(Industries, company sizes, decision-maker roles you sell to.)

## Current strategic focus
(What matters this quarter / year: a new product, a market expansion, a hiring push, etc.)

## Competitors and adjacent players
(Names the AI should recognise as competitive context.)
"""

_DEFAULT_MARKET_SEGMENTS = """\
# Market Segments

> List the market segments your company operates in. The AI uses this to
> decide which industry signals, regulations, and competitor moves are
> actually relevant to you.

## Primary segments
- (Segment 1 — short description, key sub-categories)
- (Segment 2 — short description)

## Secondary / adjacent segments
- (Segment 3 — areas you watch but don't currently serve)

## Geographic markets
- (Countries / regions where you actively operate)

## Segments to ignore
- (Anything tangentially related that the AI should NOT prioritise)
"""


def _profile_dir(data_dir: Path) -> Path:
    return Path(data_dir) / _PROFILE_SUBDIR


def _business_path(data_dir: Path) -> Path:
    return _profile_dir(data_dir) / "business_profile.md"


def _segments_path(data_dir: Path) -> Path:
    return _profile_dir(data_dir) / "market_segments.md"


def _read_or_default(path: Path, default: str) -> str:
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default)
    return default.strip()


def load_business_profile(data_dir: Path) -> str:
    return _read_or_default(_business_path(data_dir), _DEFAULT_BUSINESS_PROFILE)


def load_market_segments(data_dir: Path) -> str:
    return _read_or_default(_segments_path(data_dir), _DEFAULT_MARKET_SEGMENTS)


def save_business_profile(data_dir: Path, text: str) -> None:
    path = _business_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n")


def save_market_segments(data_dir: Path, text: str) -> None:
    path = _segments_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n")


_VALID_STAGES = ("pending", "awaiting_confirmation", "generating", "draft_ready", "user_confirmed")
_VALID_STEP_STATUSES = ("pending", "in_progress", "done", "failed")

# Order matters — frontend renders this list top-to-bottom.
INIT_STEPS = [
    ("crm",      "Building contact database from inbox"),
    ("projects", "Detecting active projects"),
    ("profile",  "Drafting your business profile"),
]


def _status_path(data_dir: Path) -> Path:
    return _profile_dir(data_dir) / "init_status.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_steps() -> list[dict]:
    return [{"key": k, "label": l, "status": "pending"} for k, l in INIT_STEPS]


def _empty_status() -> dict:
    return {
        "stage": "pending",
        "last_update": None,
        "steps": _default_steps(),
        "current_message": "",
    }


def load_init_status(data_dir: Path) -> dict:
    path = _status_path(data_dir)
    if not path.exists():
        return _empty_status()
    try:
        data = json.loads(path.read_text())
    except Exception:
        return _empty_status()
    # Backfill missing fields for older status files
    if "steps" not in data:
        data["steps"] = _default_steps()
    if "current_message" not in data:
        data["current_message"] = ""
    return data


def _write_status(data_dir: Path, status: dict) -> None:
    path = _status_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    status["last_update"] = _now_iso()
    path.write_text(json.dumps(status, indent=2))


def save_init_status(data_dir: Path, stage: str, current_message: str | None = None) -> None:
    if stage not in _VALID_STAGES:
        raise ValueError(f"invalid stage: {stage}")
    status = load_init_status(data_dir)
    status["stage"] = stage
    if current_message is not None:
        status["current_message"] = current_message
    _write_status(data_dir, status)


def update_init_step(data_dir: Path, step_key: str, status: str, message: str = "") -> None:
    """Mark one step's status. status ∈ pending|in_progress|done|failed."""
    if status not in _VALID_STEP_STATUSES:
        raise ValueError(f"invalid step status: {status}")
    current = load_init_status(data_dir)
    for s in current["steps"]:
        if s["key"] == step_key:
            s["status"] = status
            break
    current["current_message"] = message
    _write_status(data_dir, current)


def update_init_message(data_dir: Path, message: str) -> None:
    """Update only the live progress message (called from inner builders' progress_cb)."""
    current = load_init_status(data_dir)
    current["current_message"] = message
    _write_status(data_dir, current)


def reset_init_steps(data_dir: Path) -> None:
    """Reset all steps to pending (used when regenerating)."""
    current = load_init_status(data_dir)
    current["steps"] = _default_steps()
    current["current_message"] = ""
    _write_status(data_dir, current)


def is_profile_confirmed(data_dir: Path) -> bool:
    return load_init_status(data_dir).get("stage") == "user_confirmed"


def init_has_started(data_dir: Path) -> bool:
    """True if init_status.json exists — i.e. the chain has been triggered at least once."""
    return _status_path(data_dir).exists()


def load_profile_context(data_dir: Path) -> str:
    """Combined text injected into AI prompts. Empty if both files are still default templates."""
    business = load_business_profile(data_dir)
    segments = load_market_segments(data_dir)

    if business == _DEFAULT_BUSINESS_PROFILE.strip() and segments == _DEFAULT_MARKET_SEGMENTS.strip():
        return ""

    parts = []
    if business and business != _DEFAULT_BUSINESS_PROFILE.strip():
        parts.append(f"## Business Profile\n{business}")
    if segments and segments != _DEFAULT_MARKET_SEGMENTS.strip():
        parts.append(f"## Market Segments\n{segments}")
    return "\n\n".join(parts)
