"""Per-chunk loop implementation for Pipeline.run (Phase 1b).

Extracted from pipeline/__init__.py to keep each file under the 200-LOC ceiling.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.alignment.segmenter import segment as _segment
from app.services.alignment.sentence_carryover import (
    split_last_open_sentence,
    words_from_segment,
)
from app.services.transcription.audio_chunking import (
    ChunkSpec,
    clip_to_valid_interval,
)
from app.services.transcription.whisper import WhisperTransientError
from app.services.transcription.youtube_audio import PipelineError

if TYPE_CHECKING:
    from app.services.pipeline import Pipeline

logger = logging.getLogger(__name__)

_BACKOFF = [1, 2]  # seconds for attempts 0 and 1


def run_chunk_loop(
    pipeline: "Pipeline",
    video_id: str,
    audio_path: Path,
    chunk_dir: Path,
    specs: list[ChunkSpec],
    job_id: str,
) -> None:
    """Execute the per-chunk streaming loop.

    For each spec: extract → transcribe (with retry) → offset → clip →
    combine with carryover → segment → split_last_open_sentence →
    translate emit list → append_segments → update_progress.

    After the loop: flush remaining carryover buffer.
    Mutates pipeline's _jobs, _videos, _translator state via method calls.
    """
    carryover_buffer: list[dict] = []
    next_segment_idx = 0
    n = len(specs)

    for spec in specs:
        clipped = _transcribe_with_retry(pipeline, audio_path, spec, chunk_dir)
        combined = carryover_buffer + clipped

        emit: list[dict] = []
        if combined:
            segments = _segment(combined)
            held, emit = split_last_open_sentence(segments)
            carryover_buffer = words_from_segment(held) if held else []
        else:
            # Silent chunk: preserve existing carryover, emit nothing
            emit = []
            # carryover_buffer unchanged

        if emit:
            texts_en = [s["text_en"] for s in emit]
            try:
                translations = pipeline._translator.translate_batch(texts_en)
            except Exception as exc:
                raise PipelineError("TRANSLATION_ERROR", str(exc)) from exc
            for i, seg in enumerate(emit):
                seg["text_zh"] = translations[i]
                seg["idx"] = next_segment_idx + i
            pipeline._videos.append_segments(video_id, emit)
            next_segment_idx += len(emit)

        pipeline._jobs.update_progress(
            job_id, _compute_progress(spec.chunk_idx, n)
        )

    # End-of-stream flush
    if carryover_buffer:
        final_segs = _segment(carryover_buffer)
        texts_en = [s["text_en"] for s in final_segs]
        try:
            translations = pipeline._translator.translate_batch(texts_en)
        except Exception as exc:
            raise PipelineError("TRANSLATION_ERROR", str(exc)) from exc
        for i, seg in enumerate(final_segs):
            seg["text_zh"] = translations[i]
            seg["idx"] = next_segment_idx + i
        pipeline._videos.append_segments(video_id, final_segs)


def _compute_progress(chunk_idx: int, total_chunks: int) -> int:
    """probe=5, download=15, then linear over chunks to 100."""
    return 15 + (chunk_idx + 1) * 85 // total_chunks


def _transcribe_with_retry(
    pipeline: "Pipeline",
    audio_path: Path,
    spec: ChunkSpec,
    chunk_dir: Path,
) -> list[dict]:
    """Transcribe one chunk with up to 3 attempts on transient errors.

    Returns video-absolute clipped word list.
    WhisperTransientError: retried up to 3 times; on exhaustion → PipelineError.
    Other exceptions from transcribe: re-raised as PipelineError(WHISPER_ERROR).
    """
    for attempt in range(3):
        try:
            chunk_path = pipeline._extract_chunk(audio_path, spec, chunk_dir)
            raw_local = pipeline._whisper.transcribe(chunk_path)
            raw_words = [
                {**w, "start": w["start"] + spec.audio_start_sec,
                 "end": w["end"] + spec.audio_start_sec}
                for w in raw_local
            ]
            return clip_to_valid_interval(raw_words, spec)
        except WhisperTransientError as exc:
            if attempt == 2:
                raise PipelineError("WHISPER_ERROR", str(exc)) from exc
            if exc.retry_after is not None:
                time.sleep(min(exc.retry_after, 30))
            else:
                time.sleep(_BACKOFF[attempt])
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError("WHISPER_ERROR", str(exc)) from exc
    return []  # unreachable
