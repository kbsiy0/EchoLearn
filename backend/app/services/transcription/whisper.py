"""WhisperClient — wraps OpenAI whisper-1 API for audio transcription.

Returns a flat word list (same shape as Whisper's word_timestamps output):
    Word = {"text": str, "start": float, "end": float}

The client is injectable: tests pass FakeWhisperClient; production uses this.
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings

# Word type alias (informational — runtime representation is plain dict)
Word = dict  # {"text": str, "start": float, "end": float}


class WhisperClient:
    """OpenAI whisper-1 client.

    Args:
        api_key: OpenAI API key. Defaults to settings.OPENAI_API_KEY (loaded
                 from .env by pydantic-settings). Empty string is allowed for
                 tests (no real calls made).
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.OPENAI_API_KEY

    def transcribe(self, audio_path: Path) -> list[Word]:
        """Transcribe audio file via whisper-1, returning word-level timings.

        Args:
            audio_path: Path to mp3/m4a audio file.

        Returns:
            list of Word dicts: [{"text": str, "start": float, "end": float}, ...]

        Raises:
            RuntimeError: if Whisper API call fails.
        """
        import openai  # lazy import so tests without openai installed still load

        client = openai.OpenAI(api_key=self._api_key)
        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )

        words: list[Word] = []
        for word_obj in (response.words or []):
            words.append({
                "text": word_obj.word,
                "start": word_obj.start,
                "end": word_obj.end,
            })
        return words
