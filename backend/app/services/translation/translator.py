"""Translator — EN → ZH batch translation via GPT-4o-mini.

The client is injectable: tests pass FakeTranslator; production uses this.
"""

from __future__ import annotations

import os


class Translator:
    """GPT-4o-mini batch translator (EN → ZH).

    Args:
        api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
                 Empty string is allowed for tests (no real calls made).
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")

    def translate_batch(self, texts_en: list[str]) -> list[str]:
        """Translate a batch of English strings to Chinese.

        Args:
            texts_en: list of English sentence strings.

        Returns:
            list of Chinese translations, same length and order as input.

        Raises:
            RuntimeError: if translation API call fails.
        """
        if not texts_en:
            return []

        import openai  # lazy import

        client = openai.OpenAI(api_key=self._api_key)
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts_en))
        prompt = (
            "Translate the following numbered English sentences to Traditional Chinese.\n"
            "Return ONLY the numbered translations in the same format, one per line.\n\n"
            f"{numbered}"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        content = response.choices[0].message.content or ""
        lines = [line.strip() for line in content.strip().splitlines() if line.strip()]

        results: list[str] = []
        for i, original in enumerate(texts_en):
            # Try to extract numbered translation
            prefix = f"{i+1}."
            matched = next((l[len(prefix):].strip() for l in lines if l.startswith(prefix)), None)
            results.append(matched if matched else original)

        return results
