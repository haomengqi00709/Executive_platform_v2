"""
Meeting DB — stores processed meeting records for M03.

Storage layout:
  .data/{user_id}/wiki/
    _index.json           ← meeting index (meeting_id → {title, date, project_id})
    {meeting_id}.json     ← full meeting record
    transcripts/
      {meeting_id}.txt    ← raw transcript text
    _unprocessed.json     ← too_long / error records for manual review

All functions require explicit wiki_dir: Path — no global paths.
Callers own read/write; this module only provides helpers.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── Index I/O ──────────────────────────────────────────────

def load_index(wiki_dir: Path) -> dict:
    path = Path(wiki_dir) / "_index.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"meetings": {}}


def save_index(wiki_dir: Path, index: dict) -> None:
    wiki_dir = Path(wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    path = wiki_dir / "_index.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    tmp.replace(path)


# ── Meeting record I/O ─────────────────────────────────────

def load_meeting(wiki_dir: Path, meeting_id: str) -> dict | None:
    path = Path(wiki_dir) / f"{meeting_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_meeting(wiki_dir: Path, meeting: dict) -> None:
    wiki_dir = Path(wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    meeting_id = meeting["meeting_id"]
    path = wiki_dir / f"{meeting_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meeting, indent=2, ensure_ascii=False))
    tmp.replace(path)


def add_meeting(wiki_dir: Path, meeting: dict) -> bool:
    """
    Add a meeting to the DB. Deduplicates by meeting_id.
    Returns True if newly added, False if already existed.
    Updates _index.json automatically.
    """
    meeting_id = meeting.get("meeting_id", "")
    if not meeting_id:
        return False

    index = load_index(wiki_dir)
    if meeting_id in index["meetings"]:
        return False

    save_meeting(wiki_dir, meeting)
    index["meetings"][meeting_id] = {
        "title":      meeting.get("title", ""),
        "date":       meeting.get("date", ""),
        "project_id": meeting.get("project_id"),
    }
    save_index(wiki_dir, index)
    return True


def is_processed(wiki_dir: Path, meeting_id: str) -> bool:
    """Return True if meeting_id already exists in the index."""
    index = load_index(wiki_dir)
    return meeting_id in index["meetings"]


# ── Transcript I/O ─────────────────────────────────────────

def save_transcript(wiki_dir: Path, meeting_id: str, text: str) -> None:
    transcript_dir = Path(wiki_dir) / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / f"{meeting_id}.txt").write_text(text, encoding="utf-8")


def load_transcript(wiki_dir: Path, meeting_id: str) -> str | None:
    path = Path(wiki_dir) / "transcripts" / f"{meeting_id}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


# ── Unprocessed (errors / too_long) ───────────────────────

def save_unprocessed(wiki_dir: Path, record: dict) -> None:
    wiki_dir = Path(wiki_dir)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    path = wiki_dir / "_unprocessed.json"
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    ids = {r.get("meeting_id") for r in existing}
    if record.get("meeting_id") not in ids:
        existing.append(record)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


# ── Query functions ────────────────────────────────────────

def get_recent_meetings(wiki_dir: Path, days: int = 7) -> list[dict]:
    """Return all meetings from the last N days, newest first."""
    wiki_dir = Path(wiki_dir)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    index = load_index(wiki_dir)
    results = []
    for meeting_id, meta in index["meetings"].items():
        date = meta.get("date", "")
        if date >= cutoff:
            full = load_meeting(wiki_dir, meeting_id)
            if full:
                results.append(full)

    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results


def get_meeting_action_items(wiki_dir: Path, days: int = 14) -> list[dict]:
    """Return all action items from meetings in the last N days, with meeting context."""
    meetings = get_recent_meetings(wiki_dir, days=days)
    results = []
    for m in meetings:
        for item in m.get("action_items", []):
            results.append({
                **item,
                "meeting_id":    m.get("meeting_id", ""),
                "meeting_title": m.get("title", ""),
                "meeting_date":  m.get("date", ""),
                "project_id":    m.get("project_id"),
            })
    return results
