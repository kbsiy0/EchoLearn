from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2

SYSTEM_PROMPT = (
    "You are a translator. Translate English sentences to "
    "Traditional Chinese (繁體中文).\n\n"
    "Rules:\n"
    "- Return a JSON object: {\"translations\": [\"...\", \"...\"]}\n"
    "- The array MUST have EXACTLY the same number of items as the input\n"
    "- Translate each numbered sentence 1-to-1, never merge or skip\n"
    "- Maintain the same order"
)


def _translate_batch(client: OpenAI, texts: list[str], context: list[str] | None = None) -> list[str]:
    """Translate a batch of English texts to Traditional Chinese.

    Uses numbered format to prevent GPT from merging similar sentences.
    Retries up to MAX_RETRIES times with exponential backoff.
    """
    last_error: Exception | None = None

    # Build numbered input so GPT knows exact count
    numbered = [f"{i+1}. {t}" for i, t in enumerate(texts)]
    user_content = "\n".join(numbered)

    if context:
        ctx_text = "\n".join(context)
        user_content = (
            f"Context (preceding sentences, do NOT translate):\n{ctx_text}\n\n"
            f"Translate these {len(texts)} sentences:\n{user_content}"
        )
    else:
        user_content = f"Translate these {len(texts)} sentences:\n{user_content}"

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()

            parsed = json.loads(content)

            # Accept both {"translations": [...]} and plain [...]
            if isinstance(parsed, dict):
                translations = parsed.get("translations", [])
            elif isinstance(parsed, list):
                translations = parsed
            else:
                raise ValueError(f"Unexpected response type: {type(parsed)}")

            if not isinstance(translations, list):
                raise ValueError(f"translations is not a list: {type(translations)}")

            if len(translations) == len(texts):
                return translations

            # Recovery: if we got fewer, pad with original text as fallback
            if len(translations) < len(texts):
                logger.warning(
                    f"Got {len(translations)}/{len(texts)} translations, padding missing ones"
                )
                while len(translations) < len(texts):
                    translations.append(texts[len(translations)])
                return translations

            # If we got more, truncate
            if len(translations) > len(texts):
                logger.warning(
                    f"Got {len(translations)}/{len(texts)} translations, truncating"
                )
                return translations[:len(texts)]

        except Exception as e:
            last_error = e
            logger.warning(
                f"Translation attempt {attempt + 1}/{MAX_RETRIES} failed: {e}"
            )
            if attempt < MAX_RETRIES - 1:
                sleep_time = BASE_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(sleep_time)

    raise ValueError(f"OPENAI_ERROR: Translation failed after {MAX_RETRIES} retries: {last_error}")


def translate_segments(segments: list[dict]) -> list[dict]:
    """Translate English text in segments to Traditional Chinese.

    Each batch includes up to 2 preceding sentences as context (not translated).

    Args:
        segments: List of dicts, each must have a "text" key with English text.

    Returns:
        The same list of segments with "text_zh" added to each.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i : i + BATCH_SIZE]
        texts = [seg["text"] for seg in batch]

        # Build context from preceding sentences (up to 2)
        context_lines = []
        for j in range(max(0, i - 2), i):
            context_lines.append(segments[j]["text"])

        translations = _translate_batch(client, texts, context_lines)

        for seg, zh_text in zip(batch, translations):
            seg["text_zh"] = zh_text

    return segments
