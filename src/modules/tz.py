"""
Shared timezone helpers — single source of truth for all date/time math.

Reads settings.json["timezone"] (IANA name written by frontend X-Timezone
header on every page load). Falls back to UTC when the user has never
hit the frontend or settings is missing.

All section code should import from here instead of rolling its own
ZoneInfo / datetime.now() / date.today() — those default to OS local
time and silently drift away from the user's actual timezone.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_UTC = ZoneInfo("UTC")


def get_user_tz(data_dir: Path) -> ZoneInfo:
    """Resolve the user's IANA timezone from settings.json. UTC on any error."""
    try:
        path = Path(data_dir) / "settings.json"
        if not path.exists():
            return _UTC
        name = (json.loads(path.read_text()) or {}).get("timezone") or "UTC"
        return ZoneInfo(name)
    except Exception:
        return _UTC


def now_local(data_dir: Path) -> datetime:
    """Timezone-aware datetime in the user's local zone."""
    return datetime.now(get_user_tz(data_dir))


def today_local_str(data_dir: Path) -> str:
    """User's local calendar date as 'YYYY-MM-DD'."""
    return now_local(data_dir).strftime("%Y-%m-%d")


def local_day_window_utc(data_dir: Path, day_offset: int = 0) -> tuple[str, str]:
    """Return (start_utc, end_utc) ISO strings covering the user's local day.

    day_offset: 0 = today, -1 = yesterday, +1 = tomorrow.
    Used to bound Graph calendar / mail queries on calendar-day boundaries
    that match the user's wall clock — not the server's OS timezone.
    """
    tz = get_user_tz(data_dir)
    midnight_today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start_local = midnight_today + timedelta(days=day_offset)
    end_local = start_local + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (
        start_local.astimezone(timezone.utc).strftime(fmt),
        end_local.astimezone(timezone.utc).strftime(fmt),
    )


def format_local_time(iso_utc: str, tz: ZoneInfo, fmt: str = "%H:%M") -> str:
    """Format a UTC ISO timestamp as user-local wall-clock time.

    Takes an explicit ZoneInfo (not data_dir) so callers in a loop can
    resolve tz once and reuse it without repeated disk reads.
    """
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime(fmt)
    except Exception:
        return iso_utc[11:16] if len(iso_utc) >= 16 else iso_utc
