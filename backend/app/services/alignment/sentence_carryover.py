"""Sentence carryover helpers for cross-chunk boundary handling.

When a chunk ends mid-sentence, the last open segment must be carried
over to the next chunk and merged with its leading words before being
emitted.  This module provides pure functions with no I/O or DB access.
"""

from typing import Any, Optional

Word = dict[str, Any]   # {"text": str, "start": float, "end": float}

# Mirror of segmenter.py's punctuation rule — keep in sync if that ever moves.
_CLOSING_QUOTES = '"”’\''
_PUNCT_ENDINGS = ('.', '!', '?')


def split_last_open_sentence(
    segments: list[dict],
) -> tuple[Optional[dict], list[dict]]:
    """Split off the last segment if it ends mid-sentence.

    Args:
        segments: list of segment dicts produced by segmenter.segment().

    Returns:
        A ``(held, emitted)`` tuple where *held* is the last segment when
        its ``text_en`` does not end with a sentence terminator (.!?),
        otherwise ``None``.  *emitted* is the remaining segments to be
        persisted for the current chunk.  An empty input returns
        ``(None, [])``.
    """
    if not segments:
        return (None, [])

    last = segments[-1]
    tail = last["text_en"].rstrip().rstrip(_CLOSING_QUOTES)
    if tail.endswith(_PUNCT_ENDINGS):
        return (None, segments)

    return (last, segments[:-1])


def words_from_segment(seg: dict) -> list[Word]:
    """Return a shallow copy of the word list from a segment dict.

    Args:
        seg: a segment dict containing a ``words`` key.

    Returns:
        A new list containing the same word dicts (shallow copy).
        Mutating the returned list does not affect *seg*.
    """
    return list(seg["words"])
