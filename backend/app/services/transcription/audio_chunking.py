"""audio_chunking — schedule and clip helpers for segmented transcription.

Public API: ChunkSpec, compute_schedule, clip_to_valid_interval, extract_chunk.
Constants:  FIRST_CHUNK_SEC=60, REST_CHUNK_SEC=300, OVERLAP_SEC=3.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIRST_CHUNK_SEC: int = 60
REST_CHUNK_SEC: int = 300
OVERLAP_SEC: int = 3

Word = dict[str, Any]  # {"text": str, "start": float, "end": float}


@dataclass(frozen=True)
class ChunkSpec:
    """One audio chunk: extraction range + valid word window."""

    chunk_idx: int
    audio_start_sec: float
    audio_end_sec: float
    valid_start_sec: float
    valid_end_sec: float
    is_first: bool
    is_last: bool


def compute_schedule(duration_sec: float) -> list[ChunkSpec]:
    """Return ordered ChunkSpecs for a video of given duration (pure)."""
    if duration_sec <= FIRST_CHUNK_SEC:
        return [_build_chunk(0, 0.0, duration_sec, duration_sec, True, True)]

    # Build valid-interval boundaries: 0, 60, 360, 660, ...
    boundaries: list[float] = [0.0, float(FIRST_CHUNK_SEC)]
    while boundaries[-1] < duration_sec:
        next_b = boundaries[-1] + REST_CHUNK_SEC
        if next_b >= duration_sec:
            boundaries.append(duration_sec)
            break
        boundaries.append(next_b)

    n = len(boundaries) - 1  # number of chunks
    chunks: list[ChunkSpec] = []
    for i in range(n):
        v_start = boundaries[i]
        v_end = boundaries[i + 1]
        chunks.append(
            _build_chunk(i, v_start, v_end, duration_sec, i == 0, i == n - 1)
        )
    return chunks


def _build_chunk(
    idx: int,
    valid_start: float,
    valid_end: float,
    duration: float,
    is_first: bool,
    is_last: bool,
) -> ChunkSpec:
    """Build a ChunkSpec from its valid interval, applying overlap rules."""
    audio_start = 0.0 if is_first else max(0.0, valid_start - OVERLAP_SEC)
    audio_end = duration if is_last else min(duration, valid_end + OVERLAP_SEC)
    return ChunkSpec(
        chunk_idx=idx,
        audio_start_sec=audio_start,
        audio_end_sec=audio_end,
        valid_start_sec=valid_start,
        valid_end_sec=valid_end,
        is_first=is_first,
        is_last=is_last,
    )


def clip_to_valid_interval(words: list[Word], spec: ChunkSpec) -> list[Word]:
    """Filter words to valid window (asymmetric partition: strict > on lower bound).

    Non-first: keep iff w["start"] > valid_start AND w["start"] <= valid_end.
    First:     keep iff w["start"] <= valid_end (t=0 included).
    """
    def _in_valid(w: Word) -> bool:
        start_ok = True if spec.is_first else w["start"] > spec.valid_start_sec
        end_ok = w["start"] <= spec.valid_end_sec
        return start_ok and end_ok

    return [w for w in words if _in_valid(w)]


def extract_chunk(source_audio: Path, spec: ChunkSpec, out_dir: Path) -> Path:
    """Slice audio via ffmpeg and return the output path.

    Uses: ffmpeg -y -ss {start} -to {end} -i {src} -c copy
                 -avoid_negative_ts make_zero {out}
    Output: chunk_{idx:02d}.mp3 (idempotent on retry).
    out_dir is caller-provided; path safety rests with the pipeline.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
    """
    out_path = out_dir / f"chunk_{spec.chunk_idx:02d}.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{spec.audio_start_sec}",
            "-to", f"{spec.audio_end_sec}",
            "-i", str(source_audio),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ],
        check=True,
    )
    return out_path
