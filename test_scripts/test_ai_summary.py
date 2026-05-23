"""
Integration test for ai_summary section.

Run: python test_scripts/test_ai_summary.py
     python test_scripts/test_ai_summary.py --no-teams   (skip Teams post)

Requires real credentials. Reads from .data/ like the live server.
Posts result to Teams webhook if teams_webhook_url is set in settings.json.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT.parent / ".env", override=False)
load_dotenv(ROOT / ".env", override=False)

DATA_DIR = Path(ROOT.parent / ".data")

from src.auth import get_valid_access_token
from src.graph import GraphClient
from src.ai import AIClient
from src.sections.ai_summary import run
from src.tools import send_teams_message


def find_user_id() -> str:
    sessions_dir = DATA_DIR / "_sessions"
    files = sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise Exception("No session files found — log in first")
    uid = files[0].stem
    print(f"Using user: {uid}")
    return uid


def main():
    post_to_teams = "--no-teams" not in sys.argv

    user_id = find_user_id()
    token   = get_valid_access_token(user_id)
    graph   = GraphClient(token)
    ai      = AIClient()

    data_dir = DATA_DIR / user_id

    settings_path = data_dir / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}

    print(f"\nRunning ai_summary section...")
    print(f"  display_name: {settings.get('display_name', '(not set)')}")
    print(f"  timezone:     {settings.get('timezone', '(not set)')}")

    result = run(
        graph=graph,
        ai=ai,
        data_dir=data_dir,
        settings=settings,
        progress=lambda msg: print(f"  {msg}"),
    )

    print(f"\n{'─'*60}")
    print(f"STATUS:  {result['status']}")
    print(f"LAST RUN: {result['last_run']}")
    print(f"EVENTS:   {len(result.get('events', []))} calendar events")
    print(f"EMAILS:   {len(result.get('top_emails', []))} screened emails")
    print(f"ACTIONS:  {len(result.get('action_items', []))} open action items")
    print(f"\n{'─'*60}")
    print("BRIEFING:\n")
    print(result.get("briefing") or "(empty)")

    print(f"\n{'─'*60}")
    print("TODAY'S MEETINGS:")
    for e in result.get("events", []):
        start = (e.get("start") or {}).get("dateTime", "")
        print(f"  {start[11:16]}  {e.get('subject', '')}")

    print(f"\n{'─'*60}")
    print("TOP EMAILS (screened):")
    for m in result.get("top_emails", [])[:10]:
        print(f"  {m.get('from_name') or m.get('from', '')} — {m.get('subject', '')[:60]}")

    # ── Teams post ──────────────────────────────────────────
    webhook_url = settings.get("teams_webhook_url", "")
    if post_to_teams and webhook_url:
        print(f"\n{'─'*60}")
        print("Posting to Teams...")
        briefing = result.get("briefing", "")
        if briefing:
            ok = send_teams_message(briefing, webhook_url)
            print(f"  {'✓ Sent' if ok else '✗ Failed'}")
        else:
            print("  Skipped — briefing is empty")
    elif post_to_teams and not webhook_url:
        print("\n(Teams webhook not configured in settings.json — skipping post)")


if __name__ == "__main__":
    main()
