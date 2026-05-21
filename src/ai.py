import os
import time
import tempfile
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(override=True)


class AIClient:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = "gemini-2.0-flash"

    def generate(self, prompt: str) -> str:
        for attempt in range(4):
            try:
                response = self.client.models.generate_content(model=self.model, contents=prompt)
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
                        ]
                    )
                    text = response.text
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

    def extract_json(self, prompt: str) -> str:
        full_prompt = f"{prompt}\n\nRespond with valid JSON only, no markdown, no code fences."
        raw = self.generate(full_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        return raw.strip()
