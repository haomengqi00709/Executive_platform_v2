"""
Local bot test — no Teams, no OAuth needed.
Graph API tools return "Owner account not available" (expected).
Config tools, dismiss_item, and AI conversation all work fully.

Run: python test_bot.py
     python test_bot.py "what meetings do I have tomorrow"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT.parent / ".env", override=False)
load_dotenv(ROOT / ".env", override=False)

from src import bot

DATA_DIR = ROOT / ".data" / "_test_bot"
DATA_DIR.mkdir(parents=True, exist_ok=True)

state    = {}
settings = {"display_name": "Daniel", "timezone": "America/Toronto"}

def chat(text: str):
    global state
    print(f"\nYou: {text}")
    reply, state = bot.reply(
        state        = state,
        text         = text,
        graph        = None,
        owner_graph  = None,
        settings     = settings,
        wiki_dir     = None,
        data_dir     = DATA_DIR,
        user_model_path = DATA_DIR / "user_model.json",
    )
    print(f"Bot: {reply}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        chat(" ".join(sys.argv[1:]))
    else:
        # Interactive loop
        print("Bot ready. Ctrl+C to quit.\n")
        while True:
            try:
                text = input("You: ").strip()
                if text:
                    chat(text)
            except (KeyboardInterrupt, EOFError):
                print("\nBye.")
                break
