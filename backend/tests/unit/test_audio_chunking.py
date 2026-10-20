"""Tests for audio_chunking module — pure schedule and clip helpers.

Tests are ordered: compute_schedule → clip_to_valid_interval → extract_chunk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.services.transcription.audio_chunking import (
    ChunkSpec,
    compute_schedule,
    clip_to_valid_interval,
    extract_chunk,
    FIRST_CHUNK_SEC,
    REST_CHUNK_SEC,
    OVERLAP_SEC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _word(start: float, end: float) -> dict:
    return {"text": "x", "start": start, "end": end}


# ---------------------------------------------------------------------------
# compute_schedule — schedule shape
# ---------------------------------------------------------------------------

def test_compute_schedule_short_video_single_chunk():
    """45s video fits in one chunk with no overlap."""
    result = compute_schedule(45)
    assert len(result) == 1
    spec = result[0]
    assert spec == ChunkSpec(
        chunk_idx=0,
        audio_start_sec=0.0,
        audio_end_sec=45.0,
        valid_start_sec=0.0,
        valid_end_sec=45.0,
        is_first=True,
        is_last=True,
    )


def test_compute_schedule_boundary_60s_still_single_chunk():
    """Exactly 60s (== FIRST_CHUNK_SEC) must be a single chunk."""
    result = compute_schedule(60)
    assert len(result) == 1
    spec = result[0]
    assert spec.audio_start_sec == 0.0
    assert spec.audio_end_sec == 60.0
    assert spec.valid_start_sec == 0.0
    assert spec.valid_end_sec == 60.0
    assert spec.is_first is True
    assert spec.is_last is True


def test_compute_schedule_two_chunks_between_60_and_120():
    """90s video → two chunks per spec pipeline-streaming.md."""
    result = compute_schedule(90)
    assert len(result) == 2

    c0, c1 = result
    # Chunk 0: audio [0, 63], valid [0, 60]
    assert c0.chunk_idx == 0
    assert c0.audio_start_sec == 0.0
    assert c0.audio_end_sec == 63.0
    assert c0.valid_start_sec == 0.0
    assert c0.valid_end_sec == 60.0
    assert c0.is_first is True
    assert c0.is_last is False

    # Chunk 1: audio [57, 90], valid [60, 90]
    assert c1.chunk_idx == 1
    assert c1.audio_start_sec == 57.0
    assert c1.audio_end_sec == 90.0
    assert c1.valid_start_sec == 60.0
    assert c1.valid_end_sec == 90.0
    assert c1.is_first is False
    assert c1.is_last is True


def test_compute_schedule_20min_matches_five_chunk_table():
    """1200s (20 min) → 5 chunks matching design.md §2 table."""
    result = compute_schedule(1200)
    assert len(result) == 5

    expected = [
        (0,   0,   63,   0,   60),
        (1,  57,  363,  60,  360),
        (2, 357,  663, 360,  660),
        (3, 657,  963, 660,  960),
        (4, 957, 1200, 960, 1200),
    ]
    for spec, (idx, a_start, a_end, v_start, v_end) in zip(result, expected):
        assert spec.chunk_idx == idx
        assert spec.audio_start_sec == float(a_start)
        assert spec.audio_end_sec == float(a_end)
        assert spec.valid_start_sec == float(v_start)
        assert spec.valid_end_sec == float(v_end)

    assert result[0].is_first is True
    assert result[0].is_last is False
    assert result[4].is_first is False
    assert result[4].is_last is True


def test_compute_schedule_first_chunk_has_no_leading_overlap():
    """First chunk audio_start_sec must be 0 for any multi-chunk schedule."""
    result = compute_schedule(90)
    assert result[0].audio_start_sec == 0.0


def test_compute_schedule_last_chunk_audio_end_equals_duration():
    """Last chunk audio_end_sec must equal duration_sec."""
    duration = 900.0
    result = compute_schedule(duration)
    assert result[-1].audio_end_sec == duration


def test_compute_schedule_is_pure():
    """compute_schedule is a pure function; two calls return equal results."""
    a = compute_schedule(600)
    b = compute_schedule(600)
    assert a == b


# ---------------------------------------------------------------------------
# clip_to_valid_interval — boundary and partition rules
# ---------------------------------------------------------------------------

def _non_first_spec(valid_start: float = 60.0, valid_end: float = 360.0) -> ChunkSpec:
    return ChunkSpec(
        chunk_idx=1,
        audio_start_sec=max(0.0, valid_start - OVERLAP_SEC),
        audio_end_sec=valid_end + OVERLAP_SEC,
        valid_start_sec=valid_start,
        valid_end_sec=valid_end,
        is_first=False,
        is_last=False,
    )


def _first_spec(valid_end: float = 60.0) -> ChunkSpec:
    return ChunkSpec(
        chunk_idx=0,
        audio_start_sec=0.0,
        audio_end_sec=valid_end + OVERLAP_SEC,
        valid_start_sec=0.0,
        valid_end_sec=valid_end,
        is_first=True,
        is_last=False,
    )


def test_clip_excludes_word_whose_start_is_at_or_before_valid_start_for_non_first_chunk():
    """Word with start=59.5 <= valid_start=60 is excluded (belongs to prev chunk)."""
    spec = _non_first_spec()
    words = [_word(59.5, 60.4)]
    assert clip_to_valid_interval(words, spec) == []


def test_clip_excludes_word_whose_start_equals_valid_start_for_non_first_chunk():
    """Equality case: start == valid_start → excluded (strict >)."""
    spec = _non_first_spec()
    words = [_word(60.0, 60.4)]
    assert clip_to_valid_interval(words, spec) == []


def test_clip_keeps_word_whose_start_is_just_after_valid_start_for_non_first_chunk():
    """Word with start=60.01 > valid_start=60 is retained."""
    spec = _non_first_spec()
    words = [_word(60.01, 60.5)]
    assert clip_to_valid_interval(words, spec) == words


def test_clip_first_chunk_keeps_word_at_t_zero():
    """is_first=True: word at start=0 is always retained."""
    spec = _first_spec()
    words = [_word(0.0, 0.3)]
    assert clip_to_valid_interval(words, spec) == words


def test_clip_keeps_word_that_straddles_valid_end():
    """Word starting at 359.5 <= valid_end=360 is retained (straddling tail OK)."""
    spec = _non_first_spec(valid_start=60.0, valid_end=360.0)
    words = [_word(359.5, 360.6)]
    assert clip_to_valid_interval(words, spec) == words


def test_clip_drops_word_whose_start_is_beyond_valid_end():
    """Word with start=361 > valid_end=360 is excluded."""
    spec = _non_first_spec(valid_start=60.0, valid_end=360.0)
    words = [_word(361.0, 361.5)]
    assert clip_to_valid_interval(words, spec) == []


def test_clip_drops_word_fully_before_valid_start_for_non_first_chunk():
    """Word with start=55 <= valid_start=60 (non-first) is excluded."""
    spec = _non_first_spec()
    words = [_word(55.0, 56.0)]
    assert clip_to_valid_interval(words, spec) == []


def test_clip_empty_words_returns_empty():
    """Empty input returns empty list."""
    spec = _non_first_spec()
    assert clip_to_valid_interval([], spec) == []


def test_clip_is_partition_across_consecutive_chunks():
    """Union of clip results across adjacent chunks equals input (no drops, no dups)."""
    # Build two adjacent specs: chunk 0 valid [0, 60], chunk 1 valid [60, 90]
    spec0 = ChunkSpec(
        chunk_idx=0,
        audio_start_sec=0.0,
        audio_end_sec=63.0,
        valid_start_sec=0.0,
        valid_end_sec=60.0,
        is_first=True,
        is_last=False,
    )
    spec1 = ChunkSpec(
        chunk_idx=1,
        audio_start_sec=57.0,
        audio_end_sec=90.0,
        valid_start_sec=60.0,
        valid_end_sec=90.0,
        is_first=False,
        is_last=True,
    )
    # Words covering the combined range including boundary
    words = [
        _word(0.0, 0.5),
        _word(30.0, 30.5),
        _word(59.8, 60.3),   # boundary word: start < 60, belongs to chunk 0
        _word(60.0, 60.4),   # exactly at boundary: start == 60, belongs to chunk 0
        _word(60.01, 60.5),  # just after boundary: belongs to chunk 1
        _word(80.0, 80.5),
        _word(89.9, 90.0),
    ]
    clipped0 = clip_to_valid_interval(words, spec0)
    clipped1 = clip_to_valid_interval(words, spec1)

    combined = clipped0 + clipped1
    # No duplicates
    assert len(combined) == len(words)
    # All words present (same objects)
    for w in words:
        assert w in combined


# ---------------------------------------------------------------------------
# extract_chunk — canonical ffmpeg invocation (mocked subprocess)
# ---------------------------------------------------------------------------

def test_extract_chunk_calls_ffmpeg_with_canonical_args():
    """extract_chunk must call subprocess.run with the canonical ffmpeg arg list."""
    spec = ChunkSpec(
        chunk_idx=1,
        audio_start_sec=57.0,
        audio_end_sec=363.0,
        valid_start_sec=60.0,
        valid_end_sec=360.0,
        is_first=False,
        is_last=False,
    )
    source = Path("/tmp/audio.mp3")
    out_dir = Path("/tmp/chunks")

    with patch("app.services.transcription.audio_chunking.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = extract_chunk(source, spec, out_dir)

    expected_out = out_dir / "chunk_01.mp3"
    expected_args = [
        "ffmpeg", "-y",
        "-ss", f"{spec.audio_start_sec}",
        "-to", f"{spec.audio_end_sec}",
        "-i", str(source),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(expected_out),
    ]
    mock_run.assert_called_once_with(expected_args, check=True)
    assert result == expected_out


def test_extract_chunk_output_filename_uses_zero_padded_index():
    """Output file is chunk_{idx:02d}.mp3."""
    spec = ChunkSpec(
        chunk_idx=0,
        audio_start_sec=0.0,
        audio_end_sec=63.0,
        valid_start_sec=0.0,
        valid_end_sec=60.0,
        is_first=True,
        is_last=False,
    )
    source = Path("/tmp/audio.mp3")
    out_dir = Path("/tmp/chunks")

    with patch("app.services.transcription.audio_chunking.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = extract_chunk(source, spec, out_dir)

    assert result.name == "chunk_00.mp3"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def test_module_exports_expected_constants():
    """Public constants must be present with correct values."""
    assert FIRST_CHUNK_SEC == 60
    assert REST_CHUNK_SEC == 300
    assert OVERLAP_SEC == 3
