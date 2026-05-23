"""
Screener integration test — fetches real inbox and runs screen_emails().

Run: python test_screener.py
Optional: python test_screener.py 14     (last 14 days instead of 30)
          python test_screener.py 30 50  (30 days, show top 50 screened-out)
"""
import os
import sys
from collections import Counter
from pathlib import Path

V1_DATA = Path(__file__).parent.parent / ".data"
os.environ.setdefault("DATA_DIR", str(V1_DATA))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
load_dotenv(Path(__file__).parent / ".env", override=False)

sys.path.insert(0, str(Path(__file__).parent))
from src.auth import get_valid_access_token
from src.graph import GraphClient
from src.ai import AIClient
from src.modules.screener import screen_emails
from src.modules.crm import load_crm


# ── Args ──────────────────────────────────────────────────
days         = int(sys.argv[1]) if len(sys.argv) > 1 else 30
show_top     = int(sys.argv[2]) if len(sys.argv) > 2 else 30


def find_user_id() -> str:
    sessions_dir = V1_DATA / "_sessions"
    if not sessions_dir.exists():
        raise Exception(f"No sessions dir at {sessions_dir}")
    files = sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise Exception("No session files found — log in first")
    uid = files[0].stem
    print(f"Using user: {uid}")
    return uid


def _sender(msg: dict) -> str:
    ea = (msg.get("from") or {}).get("emailAddress") or {}
    name = (ea.get("name") or "").strip()
    addr = ea.get("address", "")
    return f"{name} <{addr}>" if name else addr


def main():
    user_id = find_user_id()
    token   = get_valid_access_token(user_id)
    graph   = GraphClient(token)
    ai      = AIClient()

    # Load CRM ignore list
    data_dir = V1_DATA / user_id
    try:
        crm_data = load_crm(data_dir)
        ignored_emails = {
            email for email, c in crm_data.get("contacts", {}).items()
            if c.get("ignore")
        }
    except Exception:
        ignored_emails = set()

    print(f"\nFetching inbox ({days} days)...")
    raw = graph.get_messages_since(days=days)
    print(f"Fetched {len(raw)} emails")

    if ignored_emails:
        print(f"CRM ignore list: {len(ignored_emails)} contact(s)")

    print("\nRunning screener...")
    messages = screen_emails(
        messages=raw,
        ai=ai,
        ignored_emails=ignored_emails,
        progress=lambda msg: print(f"  {msg}"),
    )

    # ── Results ───────────────────────────────────────────
    kept        = [m for m in messages if not m.get("screened_out")]
    filtered    = [m for m in messages if m.get("screened_out")]
    reason_dist = Counter(m.get("screen_reason", "") for m in filtered)

    print(f"\n{'─'*60}")
    print(f"RESULTS: {len(messages)} emails total")
    print(f"  ✅  Kept:     {len(kept)}  ({len(kept)/len(messages)*100:.0f}%)")
    print(f"  🚫  Filtered: {len(filtered)}  ({len(filtered)/len(messages)*100:.0f}%)")

    if reason_dist:
        print(f"\nFilter breakdown:")
        for reason, count in reason_dist.most_common():
            print(f"  {count:3d}  {reason}")

    # ── Show filtered emails ──────────────────────────────
    print(f"\n{'─'*60}")
    print(f"SCREENED OUT (top {min(show_top, len(filtered))}):")
    for m in filtered[:show_top]:
        subj   = (m.get("subject") or "(no subject)")[:60]
        sender = _sender(m)[:45]
        reason = m.get("screen_reason", "")
        print(f"  [{reason:22s}]  {subj:<60}  — {sender}")

    # ── Show kept emails ──────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"KEPT (top {min(show_top, len(kept))}):")
    for m in kept[:show_top]:
        subj   = (m.get("subject") or "(no subject)")[:60]
        sender = _sender(m)[:45]
        print(f"  {subj:<60}  — {sender}")

    # ── Sanity check: any obvious misses? ────────────────
    print(f"\n{'─'*60}")
    print("SANITY CHECK — kept emails that look like they might be noise:")
    noise_words = ("unsubscribe", "newsletter", "notification", "no-reply",
                   "noreply", "accepted:", "declined:", "tentative:",
                   "automatic reply", "out of office")
    suspects = [
        m for m in kept
        if any(w in (m.get("subject") or "").lower() or
               w in (((m.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
               for w in noise_words)
    ]
    if suspects:
        for m in suspects[:15]:
            subj   = (m.get("subject") or "")[:65]
            sender = _sender(m)[:45]
            print(f"  ⚠️  {subj:<65}  — {sender}")
    else:
        print("  None found — looks clean ✓")


if __name__ == "__main__":
    main()
