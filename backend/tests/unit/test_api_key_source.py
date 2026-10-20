"""API key source regression test.

Verifies WhisperClient and Translator resolve their default api_key from
`app.config.settings.OPENAI_API_KEY` rather than `os.environ` directly, so
values from `.env` (loaded by pydantic-settings) reach the OpenAI SDK.

Context: pydantic-settings reads `.env` into the Settings object without
populating `os.environ`; using `os.getenv("OPENAI_API_KEY")` therefore sees
empty string when the key is only in `.env`, causing "Connection error" on
real API calls. See change/pre-phase1-env-fixes.
"""

from __future__ import annotations


class TestWhisperClientApiKeySource:
    def test_default_reads_from_settings_when_env_absent(self, monkeypatch):
        """With os.environ cleared and settings.OPENAI_API_KEY set, client picks up settings."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.transcription.whisper import WhisperClient
        client = WhisperClient()
        assert client._api_key == "sk-from-settings"

    def test_explicit_api_key_overrides_settings(self, monkeypatch):
        """Explicit constructor arg wins over settings (injectable for tests)."""
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.transcription.whisper import WhisperClient
        client = WhisperClient(api_key="sk-explicit")
        assert client._api_key == "sk-explicit"

    def test_explicit_empty_string_allowed_for_tests(self, monkeypatch):
        """Empty string is a valid explicit value (tests pass it)."""
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.transcription.whisper import WhisperClient
        client = WhisperClient(api_key="")
        assert client._api_key == ""


class TestTranslatorApiKeySource:
    def test_default_reads_from_settings_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.translation.translator import Translator
        client = Translator()
        assert client._api_key == "sk-from-settings"

    def test_explicit_api_key_overrides_settings(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.translation.translator import Translator
        client = Translator(api_key="sk-explicit")
        assert client._api_key == "sk-explicit"

    def test_explicit_empty_string_allowed_for_tests(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-from-settings")

        from app.services.translation.translator import Translator
        client = Translator(api_key="")
        assert client._api_key == ""
