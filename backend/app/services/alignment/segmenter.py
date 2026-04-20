"""Segment a flat Whisper word list into sentence-level segments.

Algorithm (from design.md Section 3):
  - Cut on punctuation ending (.!?) when buffer duration >= 3s
  - Cut on silence gap >= 0.7s when buffer duration >= 3s
  - Hard cap: cut at 15s regardless of punctuation or silence
  - Trailing closing quotes (\", \u201d, \u2019, ') are stripped before punct check

Whitespace normalization:
  - Strip each word token
  - Drop empty tokens
  - Join with single space
  - Collapse runs of >=2 spaces via re.sub
"""

import re
from typing import Any


Word = dict[str, Any]   # {"text": str, "start": float, "end": float}
_CLOSING_QUOTES = '"\u201d\u2019\''
_PUNCT_ENDINGS = ('.', '!', '?')


def _flush(buffer: list[Word], idx: int) -> dict:
    tokens = [w["text"].strip() for w in buffer]
    tokens = [t for t in tokens if t]
    text_en = " ".join(tokens)
    text_en = re.sub(r" {2,}", " ", text_en)
    return {
        "idx": idx,
        "start": buffer[0]["start"],
        "end": buffer[-1]["end"],
        "text_en": text_en,
        "text_zh": "",
        "words": list(buffer),
    }


def segment(words: list[Word]) -> list[dict]:
    """Convert flat Whisper word list to sentence segments.

    Args:
        words: list of {"text", "start", "end"} dicts from Whisper.

    Returns:
        list of segment dicts with idx, start, end, text_en, text_zh, words.

    Raises:
        ValueError: if words is empty (no speech detected).
    """
    if not words:
        raise ValueError("no speech detected")

    buffer: list[Word] = []
    segments: list[dict] = []

    for i, w in enumerate(words):
        buffer.append(w)
        duration = buffer[-1]["end"] - buffer[0]["start"]
        next_gap = (
            words[i + 1]["start"] - w["end"] if i + 1 < len(words) else None
        )

        tail = w["text"].rstrip().rstrip(_CLOSING_QUOTES)
        should_cut = (
            (tail.endswith(_PUNCT_ENDINGS) and duration >= 3.0)
            or (next_gap is not None and next_gap >= 0.7 and duration >= 3.0)
            or duration >= 15.0
        )

        if should_cut:
            segments.append(_flush(buffer, len(segments)))
            buffer = []

    if buffer:
        segments.append(_flush(buffer, len(segments)))

    return segments
