"""
FakeTranslator — test double for backend/app/services/translation/translator.py.

The real client (Translator) will have this signature when created in T03:
    class Translator:
        def translate_batch(self, texts_en: list[str]) -> list[str]: ...

This fake matches that signature exactly so that test_fake_signatures.py can
mechanically verify parity via inspect.signature.
"""

from __future__ import annotations

from typing import Union


class FakeTranslator:
    """Controllable translator double for unit/integration tests.

    Construct with a mapping dict (en -> zh) to return translations, or an
    Exception to raise on any translate_batch call.

    Usage:
        fake = FakeTranslator(mapping={"Hello world": "你好世界"})
        results = fake.translate_batch(["Hello world"])
        assert results == ["你好世界"]

        fake_err = FakeTranslator(mapping=ValueError("TRANSLATION_ERROR: boom"))
        with pytest.raises(ValueError):
            fake_err.translate_batch(["anything"])
    """

    def __init__(self, mapping: Union[dict[str, str], Exception]) -> None:
        self._mapping = mapping

    def translate_batch(self, texts_en: list[str]) -> list[str]:
        """Return translated texts or raise the pre-configured exception.

        Unknown texts are returned untranslated (original English) as a safe
        fallback — this mirrors the production translator's padding behaviour.

        Signature must match Translator.translate_batch exactly —
        verified by tests/unit/test_fake_signatures.py via inspect.signature.
        """
        if isinstance(self._mapping, Exception):
            raise self._mapping
        return [self._mapping.get(text, text) for text in texts_en]
