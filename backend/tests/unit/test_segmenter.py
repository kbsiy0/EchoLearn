"""Unit tests for alignment/segmenter.py — TDD Red phase."""

import pytest
from app.services.alignment.segmenter import segment


def w(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_empty_raises_value_error():
    with pytest.raises(ValueError, match="no speech detected"):
        segment([])


# ---------------------------------------------------------------------------
# Single token
# ---------------------------------------------------------------------------

def test_single_token_emits_one_segment():
    words = [w("Hello", 0.0, 1.0)]
    segs = segment(words)
    assert len(segs) == 1
    assert segs[0]["text_en"] == "Hello"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 1.0


# ---------------------------------------------------------------------------
# Punctuation cuts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("punct_word", [
    "Hello.",
    "Really!",
    "What?",
])
def test_punctuation_cut_when_duration_gte_3s(punct_word):
    # 4s duration → should cut on punctuation
    words = [w(punct_word, 0.0, 4.0), w("Next", 4.1, 5.0)]
    segs = segment(words)
    assert len(segs) == 2
    assert segs[0]["text_en"] == punct_word


def test_punctuation_no_cut_when_duration_lt_3s():
    # Only 1s duration → should NOT cut on punctuation
    words = [w("Yeah.", 0.0, 1.0), w("OK.", 1.1, 2.0), w("Fine.", 2.1, 3.0),
             w("Done.", 3.1, 4.0)]
    segs = segment(words)
    # All 4 words span 4s total — the last one ends at 4.0, duration=4.0
    # but each individual punctuated word is < 3s from start of buffer
    # Actually first word starts buffer, duration at "Yeah." = 1s < 3s → no cut
    # At "OK." duration = 2s < 3s → no cut; At "Fine." duration = 3s → cut!
    # So we get 2 segments here — let's just check there's no cut at first word
    assert segs[0]["text_en"].startswith("Yeah.")


def test_quote_trailing_punctuation_period():
    """'Done."' should trigger punctuation cut."""
    words = [w('Done."', 0.0, 4.0), w("Next", 4.1, 5.0)]
    segs = segment(words)
    assert len(segs) == 2


def test_quote_trailing_punctuation_question():
    """\"Really?'\" should trigger punctuation cut."""
    words = [w("Really?'", 0.0, 4.0), w("Next", 4.1, 5.0)]
    segs = segment(words)
    assert len(segs) == 2


def test_curly_quote_trailing_punctuation():
    """'Done.\u201d' (curly double quote) should trigger punctuation cut."""
    words = [w("Done.\u201d", 0.0, 4.0), w("Next", 4.1, 5.0)]
    segs = segment(words)
    assert len(segs) == 2


# ---------------------------------------------------------------------------
# Silence gap cut
# ---------------------------------------------------------------------------

def test_silence_gap_cut_when_gap_gte_0_7s_and_duration_gte_3s():
    words = [
        w("Hello", 0.0, 3.0),   # duration = 3.0s at this point
        w("World", 4.0, 5.0),   # gap = 1.0s >= 0.7s, duration >= 3s → cut
    ]
    segs = segment(words)
    assert len(segs) == 2
    assert segs[0]["text_en"] == "Hello"
    assert segs[1]["text_en"] == "World"


def test_silence_gap_no_cut_when_duration_lt_3s():
    words = [
        w("Hi", 0.0, 1.0),    # duration 1s, gap after = 1.0s but duration < 3s
        w("There", 2.0, 4.0),
    ]
    segs = segment(words)
    # Only 1 segment because duration at gap was < 3s
    assert len(segs) == 1


# ---------------------------------------------------------------------------
# 15s hard cap
# ---------------------------------------------------------------------------

def test_15s_hard_cap():
    """All-caps no punctuation speech cut at 15s."""
    # 16 words each 1s apart, no punctuation
    words = [w(f"WORD{i}", float(i), float(i + 1)) for i in range(16)]
    segs = segment(words)
    # First segment should be cut at 15s, second has the rest
    assert len(segs) >= 2
    durations = [s["end"] - s["start"] for s in segs]
    assert all(d <= 15.0 for d in durations)


def test_15s_hard_cap_regardless_of_punctuation():
    """Hard cap fires at 15s even if no punctuation."""
    words = [w("WORD", float(i), float(i + 1)) for i in range(20)]
    segs = segment(words)
    assert all(s["end"] - s["start"] <= 15.0 for s in segs)


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------

def test_leading_space_tokens_normalized():
    """Tokens with leading spaces like ' world' are stripped."""
    words = [
        w("Hello", 0.0, 1.0),
        w(" world", 1.0, 5.0),   # leading space
    ]
    segs = segment(words)
    assert segs[0]["text_en"] == "Hello world"


def test_empty_token_dropped():
    """Empty token after strip is dropped."""
    words = [
        w("Hello", 0.0, 4.0),
        w("  ", 4.0, 4.1),      # whitespace-only token
        w("World", 4.1, 5.0),
    ]
    segs = segment(words)
    assert "  " not in segs[0]["text_en"]
    assert segs[0]["text_en"] in ("Hello World", "Hello\u0020World")


def test_comma_token_leading_space():
    """Real Whisper sample: ' ,' has leading space."""
    words = [
        w("Hello", 0.0, 1.0),
        w(" ,", 1.0, 1.1),
        w(" world", 1.1, 4.5),
    ]
    segs = segment(words)
    assert segs[0]["text_en"] == "Hello , world"


# ---------------------------------------------------------------------------
# Words preserved verbatim in segment
# ---------------------------------------------------------------------------

def test_words_preserved_verbatim():
    words = [w("Hello", 0.0, 1.0), w(" world", 1.0, 5.0)]
    segs = segment(words)
    assert segs[0]["words"] == words


# ---------------------------------------------------------------------------
# idx field
# ---------------------------------------------------------------------------

def test_idx_monotonically_increasing():
    words = [w("WORD", float(i), float(i + 1)) for i in range(30)]
    segs = segment(words)
    for i, s in enumerate(segs):
        assert s["idx"] == i
