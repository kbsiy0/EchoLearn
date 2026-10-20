"""WhisperClient — wraps OpenAI whisper-1 API for audio transcription.

Returns a flat word list (same shape as Whisper's word_timestamps output):
    Word = {"text": str, "start": float, "end": float}

The client is injectable: tests pass FakeWhisperClient; production uses this.

WhisperTransientError is raised for retry-eligible failures:
    openai.APIConnectionError, openai.APITimeoutError,
    openai.RateLimitError (HTTP 429), openai.APIStatusError with status >= 500.
Non-retry-eligible exceptions (e.g. 4xx other than 429, ValueError) pass through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings

# Word type alias (informational — runtime representation is plain dict)
Word = dict  # {"text": str, "start": float, "end": float}


class WhisperTransientError(Exception):
    """Raised for retry-eligible Whisper failures.

    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header),
                     or None to use the default backoff schedule (1s, 2s).
    """

    def __init__(self, retry_after: Optional[float] = None) -> None:
        super().__init__(f"Transient Whisper error (retry_after={retry_after})")
        self.retry_after = retry_after


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
            WhisperTransientError: for network/timeout/rate-limit/5xx failures.
            Other exceptions pass through unchanged (4xx non-429, bad path, etc.)
        """
        import openai  # lazy import so tests without openai installed still load

        client = openai.OpenAI(api_key=self._api_key)
        try:
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
        except openai.RateLimitError as exc:
            retry_after = getattr(exc, "retry_after", None)
            raise WhisperTransientError(retry_after=retry_after) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise WhisperTransientError(retry_after=None) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise WhisperTransientError(retry_after=None) from exc
            raise  # 4xx non-429 passes through

        words: list[Word] = []
        for word_obj in (response.words or []):
            words.append({
                "text": word_obj.word,
                "start": word_obj.start,
                "end": word_obj.end,
            })
        return words
