"""Pipeline package — per-chunk streaming transcription pipeline.

Public API:
    Pipeline   — class with injectable dependencies
    run        — module-level function for production use
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Callable, Optional, Protocol

from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo
from app.services.transcription.audio_chunking import (
    ChunkSpec,
    compute_schedule,
    extract_chunk as _extract_chunk,
)
from app.services.transcription.youtube_audio import (
    AUDIO_DIR,
    PipelineError,
    VideoMetadata as _VideoMetadata,
    download_audio as _download_audio,
    probe_metadata as _probe_metadata,
)
from app.services.errors import ErrorCode, safe_message
from app.services.pipeline._chunk_loop import run_chunk_loop

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class WhisperProtocol(Protocol):
    def transcribe(self, audio_path: Path) -> list[dict]: ...


class TranslatorProtocol(Protocol):
    def translate_batch(self, texts_en: list[str]) -> list[str]: ...


ProbeCallable = Callable[[str], _VideoMetadata]
DownloadCallable = Callable[[str], Path]
ExtractChunkCallable = Callable[[Path, ChunkSpec, Path], Path]


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class Pipeline:
    """Orchestrates end-to-end subtitle production for one job (per-chunk loop)."""

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        whisper: WhisperProtocol,
        translator: TranslatorProtocol,
        probe_fn: Optional[ProbeCallable] = None,
        download_fn: Optional[DownloadCallable] = None,
        extract_chunk_fn: Optional[ExtractChunkCallable] = None,
    ) -> None:
        self._jobs = JobsRepo(db_conn)
        self._videos = VideosRepo(db_conn)
        self._whisper = whisper
        self._translator = translator
        self._probe = probe_fn or _probe_metadata
        self._download = download_fn or _download_audio
        self._extract_chunk = extract_chunk_fn or _extract_chunk

    def run(self, job_id: str) -> None:
        """Execute the full streaming pipeline for job_id."""
        job = self._jobs.get(job_id)
        if job is None:
            logger.error("Pipeline.run: job %s not found", job_id)
            return

        audio_path: Optional[Path] = None
        chunk_dir: Optional[Path] = None

        try:
            self._jobs.update_status(job_id, "processing")

            # Stage 1: probe → 5%
            video_id = job["video_id"]
            url = f"https://www.youtube.com/watch?v={video_id}"
            meta = self._probe(url)
            video_id = meta.video_id
            self._jobs.update_progress(job_id, 5)

            # Stage 2: upsert video row + clear old segments
            self._videos.upsert_video_clear_segments(
                video_id, meta.title, meta.duration_sec, meta.source
            )

            # Stage 3: download → 15%
            audio_path = self._download(video_id)
            self._jobs.update_progress(job_id, 15)

            # Stage 4: per-chunk loop
            chunk_dir = AUDIO_DIR / f"chunks_{video_id}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            specs = compute_schedule(meta.duration_sec)

            run_chunk_loop(
                self, video_id, audio_path, chunk_dir, specs, job_id
            )

            self._jobs.update_status(job_id, "completed")

        except PipelineError as exc:
            logger.warning("Pipeline failed [%s]: %s", exc.error_code, exc.message)
            self._jobs.update_status(
                job_id, "failed",
                error_code=exc.error_code,
                error_message=safe_message(exc.error_code),
            )

        except Exception as exc:
            logger.warning("Pipeline internal error for job %s: %s", job_id, exc)
            self._jobs.update_status(
                job_id, "failed",
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message=safe_message(ErrorCode.INTERNAL_ERROR),
            )

        finally:
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)
            if chunk_dir is not None:
                shutil.rmtree(chunk_dir, ignore_errors=True)


def run(job_id: str) -> None:
    """Run pipeline using real clients from environment."""
    from app.db.connection import get_connection
    from app.services.transcription.whisper import WhisperClient
    from app.services.translation.translator import Translator

    conn = get_connection()
    Pipeline(
        db_conn=conn,
        whisper=WhisperClient(),
        translator=Translator(),
    ).run(job_id)
