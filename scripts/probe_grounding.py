#!/usr/bin/env python3
"""Make ONE grounded Gemini call and dump the raw grounding_metadata structure.

  GEMINI_API_KEY=<key> python -m scripts.probe_grounding <model>

Why: 3.5-flash returns grounded answers but reports 0 web_search_queries in our
meter, while 2.5-flash returns the query list. This probe shows EXACTLY which
fields the response's grounding_metadata carries per model, so we can say
definitively whether 3.5 omits web_search_queries (untraceable from our end) or
just exposes it under a different field.
"""
import os
import sys

from google import genai
from google.genai import types

PROMPT = ("What are the most notable business news, partnerships, or executive "
          "announcements for Stantec, WSP Global, and Arup in the last 30 days? "
          "Search the web and summarize briefly.")


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash"
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    print(f"=== model={model} ===")
    resp = client.models.generate_content(
        model=model, contents=PROMPT,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]),
    )
    um = getattr(resp, "usage_metadata", None)
    if um:
        print(f"usage: prompt={getattr(um,'prompt_token_count',0)} "
              f"candidates={getattr(um,'candidates_token_count',0)} "
              f"thoughts={getattr(um,'thoughts_token_count',0)} "
              f"total={getattr(um,'total_token_count',0)}")
    for i, c in enumerate(getattr(resp, "candidates", None) or []):
        gm = getattr(c, "grounding_metadata", None)
        print(f"\n--- candidate[{i}] grounding_metadata = {type(gm).__name__ if gm else None} ---")
        if gm is None:
            print("  (no grounding_metadata on this candidate)")
            continue
        # Dump every non-None attribute name + a short repr of its value.
        for attr in sorted(dir(gm)):
            if attr.startswith("_"):
                continue
            try:
                v = getattr(gm, attr)
            except Exception:
                continue
            if callable(v) or v is None:
                continue
            if isinstance(v, (list, tuple)):
                print(f"  {attr}: list(len={len(v)}) -> {[str(x)[:60] for x in v[:8]]}")
            else:
                print(f"  {attr}: {str(v)[:120]}")
    print(f"\ntext[:300]: {(resp.text or '')[:300]!r}")


if __name__ == "__main__":
    main()
