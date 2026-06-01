import os
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(override=True)


# Single source of truth for the Gemini model across the whole app.
# Sections read it via AIClient.model; the Teams bot imports this constant directly.
# Change the model in ONE place: this default, or the GEMINI_MODEL env var
# (lets you switch models on Railway/Azure without a redeploy).
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


# Per-call timeout for Gemini text generation. If the API hangs (rare but happens),
# we abandon the call and let the retry logic try again instead of blocking forever.
_GEMINI_TIMEOUT_SECS = 60


def _call_with_timeout(fn, timeout_secs: int):
    """Run fn() in a worker thread, raise TimeoutError if it doesn't finish in time.
    Note: cannot truly kill the worker thread — it'll keep running in background until
    the underlying network call finally returns or errors out. But the caller is unblocked."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_secs)
        except _FutureTimeout:
            raise TimeoutError(f"Gemini call exceeded {timeout_secs}s")


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
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=[
                            types.Part.from_uri(file_uri=uploaded.uri, mime_type="audio/mpeg"),
                            "Transcribe all speech in this audio. Label each speaker as 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                        ],
                        # Long meetings can easily exceed Gemini's default ~8K output cap;
                        # 65535 is the model max. Without this the transcript gets silently
                        # cut off and only the early portion survives.
                        config=types.GenerateContentConfig(max_output_tokens=65535),
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
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=[
                            types.Part.from_uri(file_uri=uploaded.uri, mime_type="video/mp4"),
                            "Transcribe all speech in this video. Label each speaker by name if visible, otherwise 'Speaker 1', 'Speaker 2', etc. Include timestamps. Be complete and accurate.",
                        ],
                        # Same fix as transcribe_audio — without this Gemini truncates
                        # long meetings at the ~8K default output cap.
                        config=types.GenerateContentConfig(max_output_tokens=65535),
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
        """Generate content with Google Search grounding (real-time web search)."""
        for attempt in range(4):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                text = response.text
                if not text or not text.strip():
                    if attempt < 3:
                        time.sleep(5)
                        continue
                    raise ValueError("Gemini returned empty response")
                return text
            except Exception as e:
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
