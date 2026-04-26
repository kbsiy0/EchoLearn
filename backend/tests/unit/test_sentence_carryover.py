"""Unit tests for sentence_carryover module.

Tests for split_last_open_sentence and words_from_segment helpers.
"""

import pytest

from app.services.alignment.sentence_carryover import (
    split_last_open_sentence,
    words_from_segment,
)


def _seg(text_en: str, words=None):
    """Build a minimal segment dict for testing."""
    return {
        "text_en": text_en,
        "words": words if words is not None else [],
    }


def _word(text: str, start: float = 0.0, end: float = 0.1):
    return {"text": text, "start": start, "end": end}


# ---------------------------------------------------------------------------
# split_last_open_sentence
# ---------------------------------------------------------------------------


def test_clean_terminator_returns_none_held():
    seg = _seg("Hi world.")
    result = split_last_open_sentence([seg])
    assert result == (None, [seg])


def test_missing_terminator_returns_held():
    seg = _seg("hello there", words=[_word("hello"), _word("there")])
    held, emitted = split_last_open_sentence([seg])
    assert held == seg
    assert emitted == []


def test_mixed_last_open():
    seg_ok1 = _seg("First sentence.")
    seg_ok2 = _seg("Second sentence!")
    seg_open = _seg("Third incomplete", words=[_word("Third"), _word("incomplete")])
    held, emitted = split_last_open_sentence([seg_ok1, seg_ok2, seg_open])
    assert held == seg_open
    assert emitted == [seg_ok1, seg_ok2]


def test_closing_quote_after_period_treated_as_terminated():
    seg = _seg('She said "hi."')
    held, emitted = split_last_open_sentence([seg])
    assert held is None
    assert emitted == [seg]


@pytest.mark.parametrize("text_en", [
    'She said “hi.”',   # U+201D right double quotation mark
    "She said ‘hi.’",   # U+2019 right single quotation mark
    "She said 'hi.'",              # ASCII single quote
])
def test_unicode_closing_quotes_after_terminator_treated_as_terminated(text_en):
    seg = _seg(text_en)
    held, emitted = split_last_open_sentence([seg])
    assert held is None
    assert emitted == [seg]


def test_empty_list_returns_none_empty():
    assert split_last_open_sentence([]) == (None, [])


def test_question_mark_terminator():
    seg = _seg("Are you sure?")
    held, emitted = split_last_open_sentence([seg])
    assert held is None
    assert emitted == [seg]


def test_exclamation_terminator():
    seg = _seg("Watch out!")
    held, emitted = split_last_open_sentence([seg])
    assert held is None
    assert emitted == [seg]


# ---------------------------------------------------------------------------
# words_from_segment
# ---------------------------------------------------------------------------


def test_words_from_segment_returns_a_copy_not_reference():
    w1 = _word("hello", 0.0, 0.5)
    w2 = _word("world", 0.6, 1.0)
    seg = _seg("hello world", words=[w1, w2])

    result = words_from_segment(seg)
    assert result == [w1, w2]

    # Mutate the returned list — original segment must be unaffected.
    result.append({"text": "x", "start": 0, "end": 0})
    assert len(seg["words"]) == 2
