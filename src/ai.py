import os
import time
import tempfile
import threading
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(override=True)


# Single source of truth for the Gemini model across the whole app.
# Sections read it via AIClient.model; the Teams bot imports this constant directly.
# Change the model in ONE place: this default, or the GEMINI_MODEL env var
# (lets you switch models on Railway/Azure without a redeploy).
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


# Default per-call timeouts. Text generation should always return quickly;
# video/audio transcription is heavier so callers pass a larger value.
_GEMINI_TIMEOUT_SECS = 60


def _call_with_timeout(fn, timeout_secs: int):
    """Run fn() in a daemon thread, raise TimeoutError if it doesn't finish in time.

    The naive implementation `with ThreadPoolExecutor() as ex` does NOT work for
    this purpose: the executor's __exit__ calls shutdown(wait=True) which blocks
    on the worker thread even after future.result(timeout=...) raises. When the
    underlying network call is stuck (Gemini occasionally hangs without erroring),
    the worker never returns, so the `with` block never exits and the caller is
    pinned indefinitely — defeating the entire point of the timeout. We hit this
    in production: a single hung crm.py contact enrichment held the init chain
    silent for ~10 minutes before being noticed.

    Daemon thread fix: spawn fn() on its own daemon thread, join with a timeout,
    and on expiry just walk away. The thread is leaked (Python can't kill a
    blocked C-extension call from the outside) but daemon=True means it won't
    block process exit, and the underlying call will eventually hit its own TCP
    timeout. Memory leak per stuck call is acceptable since timeouts should be
    rare.
    """
    result: dict = {}
    def runner():
        try:
            result["value"] = fn()
        except BaseException as e:
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
                    lambda: self.client.models.generate_content(model=self.model, contents=prompt),
                    _GEMINI_TIMEOUT_SECS,
                )
                text = response.text
                if not text or not text.strip():
                    if attempt < 3:
                        time.sleep(5)
                        continue
                    raise ValueError("Gemini returned empty response")
                return text
            except Exception as e:
                err = str(e)
                # Timeout = hang. Only retry ONCE — don't waste 4 minutes per stuck call.
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        print(f"  Gemini timeout after {_GEMINI_TIMEOUT_SECS}s, retrying once...")
                        time.sleep(3)
                        continue
                    print(f"  Gemini timeout twice — giving up.")
                    raise
                if "429" in err and attempt < 3:
                    wait = 10 * (2 ** attempt)
                    print(f"  Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                elif attempt < 3:
                    time.sleep(5)
                else:
                    raise

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "recording.mp3") -> str:
        """Transcribe an audio file (mp3/m4a)."""
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            uploaded = self.client.files.upload(file=tmp_path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(5)
                uploaded = self.client.files.get(name=uploaded.name)
            for attempt in range(3):
                try:
                    # Audio transcription can legitimately take a few minutes for
                    # long meetings — 5 min ceiling per attempt is enough room
                    # while still bounding catastrophic hangs.
                    response = _call_with_timeout(
                        lambda: self.client.models.generate_content(
                            model=self.model,
                            contents=[
                                types.Part.from_uri(file_uri=uploaded.uri, mime_type="audio/mpeg"),
                                "Transcribe all speech in this audio. Label each speaker as 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                            ],
                            # Long meetings can easily exceed Gemini's default ~8K output cap;
                            # 65535 is the model max. Without this the transcript gets silently
                            # cut off and only the early portion survives.
                            config=types.GenerateContentConfig(max_output_tokens=65535),
                        ),
                        timeout_secs=300,
                    )
                    text = response.text
                    # If the model hit the output limit we still got partial text — log it
                    # so we can spot truncated meetings in the operational logs.
                    try:
                        fr = (response.candidates or [None])[0]
                        finish = getattr(fr, "finish_reason", None) if fr else None
                        if finish and str(finish).upper().endswith("MAX_TOKENS"):
                            print(f"[ai.transcribe_audio] WARN: hit MAX_TOKENS on {filename} — transcript may be truncated")
                    except Exception:
                        pass
                    if text and text.strip():
                        return text
                    if attempt < 2:
                        time.sleep(5)
                except Exception as e:
                    if "429" in str(e) and attempt < 2:
                        time.sleep(10 * (2 ** attempt))
                    elif attempt < 2:
                        time.sleep(5)
                    else:
                        raise
            raise ValueError(f"Gemini returned empty transcription for {filename}")
        finally:
            os.unlink(tmp_path)

    def transcribe_video(self, video_bytes: bytes, filename: str = "recording.mp4") -> str:
        """Upload MP4 to Gemini Files API, poll until ready, then transcribe."""
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(video_bytes)
            tmp_path = f.name
        try:
            uploaded = self.client.files.upload(file=tmp_path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(5)
                uploaded = self.client.files.get(name=uploaded.name)
            for attempt in range(3):
                try:
                    # See transcribe_audio re. 5 min ceiling.
                    response = _call_with_timeout(
                        lambda: self.client.models.generate_content(
                            model=self.model,
                            contents=[
                                types.Part.from_uri(file_uri=uploaded.uri, mime_type="video/mp4"),
                                "Transcribe all speech in this video. Label each speaker by name if visible, otherwise 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                            ],
                            # Same fix as transcribe_audio — without this Gemini truncates
                            # long meetings at the ~8K default output cap.
                            config=types.GenerateContentConfig(max_output_tokens=65535),
                        ),
                        timeout_secs=300,
                    )
                    text = response.text
                    try:
                        fr = (response.candidates or [None])[0]
                        finish = getattr(fr, "finish_reason", None) if fr else None
                        if finish and str(finish).upper().endswith("MAX_TOKENS"):
                            print(f"[ai.transcribe_video] WARN: hit MAX_TOKENS on {filename} — transcript may be truncated")
                    except Exception:
                        pass
                    if text and text.strip():
                        return text
                    if attempt < 2:
                        time.sleep(5)
                except Exception as e:
                    if "429" in str(e) and attempt < 2:
                        time.sleep(10 * (2 ** attempt))
                    elif attempt < 2:
                        time.sleep(5)
                    else:
                        raise
            raise ValueError(f"Gemini returned empty transcription for {filename}")
        finally:
            os.unlink(tmp_path)

    def generate_with_search(self, prompt: str) -> str:
        """Generate content with Google Search grounding (real-time web search).
        Search-grounded calls can be slower than plain generate; use the same
        60s budget as generate() with one retry on timeout."""
        for attempt in range(4):
            try:
                response = _call_with_timeout(
                    lambda: self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                        ),
                    ),
                    _GEMINI_TIMEOUT_SECS,
                )
                text = response.text
                if not text or not text.strip():
                    if attempt < 3:
                        time.sleep(5)
                        continue
                    raise ValueError("Gemini returned empty response")
                return text
            except Exception as e:
                if isinstance(e, TimeoutError):
                    if attempt < 1:
                        print(f"  Gemini search timeout after {_GEMINI_TIMEOUT_SECS}s, retrying once...")
                        time.sleep(3)
                        continue
                    print(f"  Gemini search timeout twice — giving up.")
                    raise
                if "429" in str(e) and attempt < 3:
                    wait = 10 * (2 ** attempt)
                    print(f"  Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                elif attempt < 3:
                    time.sleep(5)
                else:
                    raise

    def extract_json(self, prompt: str) -> str:
        full_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown, no code fences."
        raw = self.generate(full_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        return raw.strip()
