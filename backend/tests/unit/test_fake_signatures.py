"""
Signature enforcement tests.

Verifies that FakeWhisperClient and FakeTranslator expose exactly the same
method signatures as the real clients declared in the pipeline spec:

    WhisperClient.transcribe(self, audio_path: Path) -> list[Word]
    Translator.translate_batch(self, texts_en: list[str]) -> list[str]

Since the real clients (WhisperClient, Translator) do not exist yet in T01,
we compare each fake's signature against a reference stub defined here that
mirrors the spec exactly. When T03 creates the real modules, a second test
class below will also compare the fake against the real implementation.

Strategy: inspect.signature strips `self` and compares parameter names,
kinds, and annotations. This catches renames like (audio_path -> path) or
type changes like (list[str] -> Sequence[str]).
"""

import inspect
from pathlib import Path


# ---------------------------------------------------------------------------
# Reference stubs — represent the spec-declared signature for each real client
# ---------------------------------------------------------------------------

class _SpecWhisperClient:
    """Stub mirroring the WhisperClient contract from specs/pipeline.md."""
    def transcribe(self, audio_path: Path) -> list:  # list[Word]
        ...


class _SpecTranslator:
    """Stub mirroring the Translator contract from specs/pipeline.md."""
    def translate_batch(self, texts_en: list) -> list:  # list[str] -> list[str]
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _param_names(method) -> list[str]:
    sig = inspect.signature(method)
    return [name for name in sig.parameters if name != "self"]


def _param_kinds(method) -> dict[str, inspect.Parameter.kind]:
    sig = inspect.signature(method)
    return {
        name: p.kind
        for name, p in sig.parameters.items()
        if name != "self"
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFakeWhisperClientSignature:
    """FakeWhisperClient.transcribe must match the spec's WhisperClient.transcribe."""

    def test_transcribe_parameter_names(self):
        from tests.fakes.whisper import FakeWhisperClient
        fake_params = _param_names(FakeWhisperClient.transcribe)
        spec_params = _param_names(_SpecWhisperClient.transcribe)
        assert fake_params == spec_params, (
            f"FakeWhisperClient.transcribe params {fake_params} != "
            f"spec params {spec_params}"
        )

    def test_transcribe_parameter_kinds(self):
        from tests.fakes.whisper import FakeWhisperClient
        fake_kinds = _param_kinds(FakeWhisperClient.transcribe)
        spec_kinds = _param_kinds(_SpecWhisperClient.transcribe)
        assert fake_kinds == spec_kinds, (
            f"FakeWhisperClient.transcribe param kinds mismatch: "
            f"{fake_kinds} != {spec_kinds}"
        )

    def test_transcribe_accepts_path_argument(self):
        """Smoke-test: calling with a Path does not raise TypeError."""
        from tests.fakes.whisper import FakeWhisperClient
        fake = FakeWhisperClient(words=[])
        result = fake.transcribe(Path("/tmp/audio.mp3"))
        assert isinstance(result, list)


class TestFakeTranslatorSignature:
    """FakeTranslator.translate_batch must match the spec's Translator.translate_batch."""

    def test_translate_batch_parameter_names(self):
        from tests.fakes.translator import FakeTranslator
        fake_params = _param_names(FakeTranslator.translate_batch)
        spec_params = _param_names(_SpecTranslator.translate_batch)
        assert fake_params == spec_params, (
            f"FakeTranslator.translate_batch params {fake_params} != "
            f"spec params {spec_params}"
        )

    def test_translate_batch_parameter_kinds(self):
        from tests.fakes.translator import FakeTranslator
        fake_kinds = _param_kinds(FakeTranslator.translate_batch)
        spec_kinds = _param_kinds(_SpecTranslator.translate_batch)
        assert fake_kinds == spec_kinds

    def test_translate_batch_returns_list(self):
        """Smoke-test: returns a list of strings equal in length to input."""
        from tests.fakes.translator import FakeTranslator
        fake = FakeTranslator(mapping={"Hello world": "你好世界"})
        result = fake.translate_batch(["Hello world"])
        assert result == ["你好世界"]

    def test_translate_batch_unknown_key_returns_original(self):
        """Unknown text falls back to original rather than raising."""
        from tests.fakes.translator import FakeTranslator
        fake = FakeTranslator(mapping={})
        result = fake.translate_batch(["unknown text"])
        assert result == ["unknown text"]

    def test_translate_batch_raises_on_exception_payload(self):
        """Exception payload is raised on translate_batch call."""
        import pytest
        from tests.fakes.translator import FakeTranslator
        fake = FakeTranslator(mapping=ValueError("TRANSLATION_ERROR: boom"))
        with pytest.raises(ValueError, match="TRANSLATION_ERROR"):
            fake.translate_batch(["anything"])


class TestFakeWhisperRaisesOnException:
    def test_transcribe_raises_on_exception_payload(self):
        import pytest
        from tests.fakes.whisper import FakeWhisperClient
        fake = FakeWhisperClient(words=ValueError("WHISPER_ERROR: boom"))
        with pytest.raises(ValueError, match="WHISPER_ERROR"):
            fake.transcribe(Path("/tmp/audio.mp3"))
