"""
FakeWhisperClient — test double for backend/app/services/transcription/whisper.py.

The real client (WhisperClient) will have this signature when created in T03:
    class WhisperClient:
        def transcribe(self, audio_path: Path) -> list[Word]: ...

Word = TypedDict("Word", {"text": str, "start": float, "end": float})

This fake matches that signature exactly so that test_fake_signatures.py can
mechanically verify parity via inspect.signature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


# Word type: matches what WhisperClient.transcribe will return.
# TypedDict is informational here; runtime representation is plain dict.
Word = dict  # {"text": str, "start": float, "end": float}


class FakeWhisperClient:
    """Controllable Whisper double for unit/integration tests.

    Construct with a list of Word dicts to return, or an Exception to raise.

    Usage:
        fake = FakeWhisperClient(words=[{"text": "Hello", "start": 0.0, "end": 0.5}])
        words = fake.transcribe(Path("/tmp/audio.mp3"))

        fake_err = FakeWhisperClient(words=ValueError("WHISPER_ERROR: boom"))
        with pytest.raises(ValueError):
            fake_err.transcribe(Path("/tmp/audio.mp3"))
    """

    def __init__(self, words: Union[list[Word], Exception]) -> None:
        self._words = words

    def transcribe(self, audio_path: Path) -> list[Word]:
        """Return the pre-configured word list or raise the pre-configured exception.

        Signature must match WhisperClient.transcribe exactly —
        verified by tests/unit/test_fake_signatures.py via inspect.signature.
        """
        if isinstance(self._words, Exception):
            raise self._words
        return list(self._words)
