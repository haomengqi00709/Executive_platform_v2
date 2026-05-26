"""
End-to-end test: re-process all 3 real OneDrive recordings with force=True,
verify CRM/Project alignment, send Teams confirmation.

Run from project root:
    python test_m03_real.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from src import auth
from src.ai import AIClient
from src.graph import GraphClient
from src.modules.m03_meeting import run as m03_run
from src.sections import recent_meetings, meeting_action_items

UID = "cd2162aa-61f2-4d28-bce1-dc2332a0a97b"
DATA_DIR = Path(f".data/{UID}")


def snap(label: str) -> dict:
    """Capture state of CRM meeting_ids + Project meeting_ids."""
    crm = json.loads((DATA_DIR / "crm.json").read_text())
    proj = json.loads((DATA_DIR / "projects.json").read_text())
    sarah = crm["contacts"].get("sarah.chen@techcorp.com", {})
    techcorp = proj["projects"].get("techcorp-erp-go-live-planning", {})
    s = {
        "sarah_meeting_ids":    sarah.get("meeting_ids", []),
        "sarah_last_contact":   sarah.get("last_contact"),
        "techcorp_meeting_ids": techcorp.get("meeting_ids", []),
    }
    print(f"\n=== {label} ===")
    print(json.dumps(s, indent=2))
    return s


def main():
    t_start = time.time()

    print("=" * 60)
    print(" M03 END-TO-END TEST — 3 real OneDrive recordings")
    print("=" * 60)

    snap("BEFORE")

    print("\nAcquiring access token + Graph client...")
    token    = auth.get_valid_access_token(UID)
    graph    = GraphClient(token)
    ai       = AIClient()
    settings = json.loads((DATA_DIR / "settings.json").read_text())

    print("Running m03_meeting.run(force=True, months=0)...")
    print("-" * 60)
    result = m03_run(
        graph, ai, DATA_DIR,
        settings=settings,
        force=True,        # reprocess even if already in wiki index
        use_mock=False,    # real OneDrive recordings
        months=0,          # no date filter — process all
    )
    print("-" * 60)

    # Refresh derived sections
    print("Refreshing recent_meetings + meeting_action_items sections...")
    recent_meetings.run(DATA_DIR)
    meeting_action_items.run(DATA_DIR)

    # Process summary
    print("\n=== Per-meeting result ===")
    for r in result.get("results", []):
        title  = r.get("title", "?")
        status = r.get("status", "?")
        pid    = r.get("project_id") or "(none)"
        n_actions = len(r.get("action_items", []))
        draft  = r.get("followup_draft_saved", False)
        link   = r.get("followup_draft_link", "")
        print(f"  • [{status}] {title[:50]}")
        print(f"      project_id: {pid}")
        print(f"      action_items: {n_actions}")
        print(f"      draft_saved: {draft}" + (f" → {link[:80]}" if link else ""))

    after = snap("AFTER")

    # Diff
    print("\n=== DIFF ===")
    print(f"sarah.chen meeting_ids: 0 → {len(after['sarah_meeting_ids'])}")
    print(f"techcorp project meeting_ids: 0 → {len(after['techcorp_meeting_ids'])}")

    # Teams notification
    print("\nSending Teams confirmation...")
    try:
        # Find the bot account linked to this owner
        sessions_dir = auth.DATA_DIR / "_sessions"
        bot_uid = None
        chat_id = None
        for f in sessions_dir.glob("*.json"):
            bp = Path(f".data") / f.stem / "teams_bot.json"
            if not bp.exists():
                continue
            bs = json.loads(bp.read_text())
            if (bs.get("enabled") and bs.get("is_registered_bot")
                    and bs.get("owner_uid") == UID and bs.get("chat_id")):
                bot_uid = f.stem
                chat_id = bs["chat_id"]
                break
        if bot_uid and chat_id:
            bot_token = auth.get_valid_access_token(bot_uid)
            bot_graph = GraphClient(bot_token)
            processed = [r for r in result.get("results", []) if r.get("status") == "processed"]
            lines = [f"✅ Meeting scan complete — {len(processed)} meeting(s) processed"]
            for r in processed:
                title = r.get("title", "(untitled)")
                date  = (r.get("date") or "")[:10]
                n_actions = len(r.get("action_items", []))
                draft_saved = r.get("followup_draft_saved", False)
                lines.append(
                    f"• **{title}**" + (f" ({date})" if date else "")
                    + f" — {n_actions} action item(s)"
                    + (" · draft saved to Drafts" if draft_saved else "")
                )
            bot_graph.send_chat_message(chat_id, "\n".join(lines))
            print(f"  → Teams message sent to chat {chat_id[:20]}...")
        else:
            print("  → No bot chat configured, skipping Teams notification")
    except Exception as e:
        print(f"  → Teams notification failed: {e}")

    elapsed = time.time() - t_start
    print(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
