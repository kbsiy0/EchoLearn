"""Unit tests for WhisperTransientError classification in WhisperClient.

Tests mock openai exception classes — NO real OpenAI calls are made.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock openai exceptions without importing real openai
# ---------------------------------------------------------------------------

def _make_openai_stubs():
    """Return a namespace of mock openai exception classes."""
    stub = types.SimpleNamespace()

    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class RateLimitError(Exception):
        def __init__(self, message="rate limit", retry_after=None):
            super().__init__(message)
            self.retry_after = retry_after

    class APIStatusError(Exception):
        def __init__(self, message="api error", status_code=500):
            super().__init__(message)
            self.status_code = status_code

    stub.APIConnectionError = APIConnectionError
    stub.APITimeoutError = APITimeoutError
    stub.RateLimitError = RateLimitError
    stub.APIStatusError = APIStatusError
    return stub


# ---------------------------------------------------------------------------
# WhisperTransientError class tests
# ---------------------------------------------------------------------------

class TestWhisperTransientErrorClass:
    def test_transient_error_is_exception(self):
        from app.services.transcription.whisper import WhisperTransientError
        err = WhisperTransientError()
        assert isinstance(err, Exception)

    def test_transient_error_default_retry_after_is_none(self):
        from app.services.transcription.whisper import WhisperTransientError
        err = WhisperTransientError()
        assert err.retry_after is None

    def test_transient_error_accepts_retry_after(self):
        from app.services.transcription.whisper import WhisperTransientError
        err = WhisperTransientError(retry_after=5.0)
        assert err.retry_after == 5.0


# ---------------------------------------------------------------------------
# WhisperClient.transcribe exception classification
# ---------------------------------------------------------------------------

class TestWhisperClientClassification:
    """Each test patches openai inside whisper.py so no real client is created."""

    def _make_client_and_openai(self, openai_stubs, call_side_effect):
        """Patch openai in whisper module and set transcription side-effect."""
        from app.services.transcription.whisper import WhisperClient
        client = WhisperClient(api_key="fake-key")

        mock_openai_mod = MagicMock()
        # Expose exception classes
        mock_openai_mod.APIConnectionError = openai_stubs.APIConnectionError
        mock_openai_mod.APITimeoutError = openai_stubs.APITimeoutError
        mock_openai_mod.RateLimitError = openai_stubs.RateLimitError
        mock_openai_mod.APIStatusError = openai_stubs.APIStatusError

        # Stub the OpenAI client so audio.transcriptions.create raises the error
        mock_openai_instance = MagicMock()
        mock_openai_mod.OpenAI.return_value = mock_openai_instance
        mock_openai_instance.audio.transcriptions.create.side_effect = call_side_effect

        return client, mock_openai_mod

    def test_api_connection_error_wrapped_as_transient(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.APIConnectionError("connection refused")
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            audio = Path("/tmp/fake.mp3")
            with pytest.raises(WhisperTransientError):
                with patch("builtins.open", MagicMock()):
                    client.transcribe(audio)

    def test_api_timeout_error_wrapped_as_transient(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.APITimeoutError("timeout")
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(WhisperTransientError):
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))

    def test_rate_limit_error_wrapped_as_transient_with_retry_after(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.RateLimitError("rate limit", retry_after=5)
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(WhisperTransientError) as exc_info:
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))
        assert exc_info.value.retry_after == 5

    def test_rate_limit_error_no_retry_after_yields_none(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.RateLimitError("rate limit", retry_after=None)
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(WhisperTransientError) as exc_info:
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))
        assert exc_info.value.retry_after is None

    def test_api_status_error_5xx_wrapped_as_transient(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.APIStatusError("server error", status_code=503)
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(WhisperTransientError):
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))

    def test_api_status_error_400_passes_through_unchanged(self):
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = stubs.APIStatusError("bad request", status_code=400)
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(stubs.APIStatusError):
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))

    def test_other_exception_passes_through_unchanged(self):
        """ValueError raised before HTTP call passes through as-is."""
        from app.services.transcription.whisper import WhisperTransientError
        stubs = _make_openai_stubs()
        exc = ValueError("bad audio path")
        client, mock_openai_mod = self._make_client_and_openai(stubs, exc)

        with patch.dict("sys.modules", {"openai": mock_openai_mod}):
            with pytest.raises(ValueError):
                with patch("builtins.open", MagicMock()):
                    client.transcribe(Path("/tmp/fake.mp3"))
