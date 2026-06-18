"""Thin Gemini wrapper — a vendored copy of the main app's AIClient.generate()
(src/ai.py:60-96) plus its daemon-thread timeout. Vendored, not imported, so this
standalone service never depends on the main program's `src/`.

Only text generation is needed here (chat), so the transcription / search / JSON
helpers are intentionally omitted.
"""
import os
import threading
import time

from google import genai

# `or` (not getenv default) so an empty GEMINI_MODEL="" env doesn't override to "".
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
_GEMINI_TIMEOUT_SECS = 60


def _call_with_timeout(fn, timeout_secs: int):
    """Run fn() on a daemon thread; raise TimeoutError if it overruns. A stuck
    Gemini call can hang indefinitely; daemon=True means a leaked worker never
    blocks process exit. (Same rationale as the main app's ai.py.)"""
    result: dict = {}

    def runner():
        try:
            result["value"] = fn()
        except BaseException as e:  # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=timeout_secs)
    if t.is_alive():
        raise TimeoutError(f"Gemini call exceeded {timeout_secs}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


class AIClient:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = DEFAULT_GEMINI_MODEL

    def generate(self, prompt: str) -> str:
        for attempt in range(4):
            try:
                response = _call_with_timeout(
                    lambda: self.client.models.generate_content(
                        model=self.model, contents=prompt
                    ),
                    _GEMINI_TIMEOUT_SECS,
                )
                text = response.text
                if not text or not text.strip():
                    if attempt < 3:
                        time.sleep(3)
                        continue
                    raise ValueError("Gemini returned empty response")
                return text
            except Exception as e:  # noqa: BLE001
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        time.sleep(2)
                        continue
                    raise
                err = str(e)
                if "429" in err and attempt < 3:
                    time.sleep(8 * (2 ** attempt))
                elif attempt < 3:
                    time.sleep(3)
                else:
                    raise
