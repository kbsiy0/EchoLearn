"""Pipeline orchestrator: probe → download → whisper → segment → translate → publish.

Progress checkpoints (from tasks.md acceptance criteria):
    5   probe_metadata done
    15  download_audio done
    45  whisper transcription done
    90  segmentation done
    95  translation done (results held in memory, not yet persisted)
    100 publish_video done (atomic upsert + segment insert)

All collaborators are injectable (constructor args) so tests use fakes.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Callable, Optional, Protocol

from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo
from app.services.alignment.segmenter import segment as _segment
from app.services.transcription.youtube_audio import (
    PipelineError,
    VideoMetadata as _VideoMetadata,
    download_audio as _download_audio,
    probe_metadata as _probe_metadata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols for dependency injection
# ---------------------------------------------------------------------------

class WhisperProtocol(Protocol):
    def transcribe(self, audio_path: Path) -> list[dict]: ...


class TranslatorProtocol(Protocol):
    def translate_batch(self, texts_en: list[str]) -> list[str]: ...


ProbeCallable = Callable[[str], _VideoMetadata]
DownloadCallable = Callable[[str], Path]


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class Pipeline:
    """Orchestrates end-to-end subtitle production for one job.

    Args:
        db_conn: SQLite connection (shared with repos).
        whisper: WhisperClient or FakeWhisperClient.
        translator: Translator or FakeTranslator.
        probe_fn: Callable matching probe_metadata signature (injectable for tests).
        download_fn: Callable matching download_audio signature (injectable for tests).
    """

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        whisper: WhisperProtocol,
        translator: TranslatorProtocol,
        probe_fn: Optional[ProbeCallable] = None,
        download_fn: Optional[DownloadCallable] = None,
    ) -> None:
        self._jobs = JobsRepo(db_conn)
        self._videos = VideosRepo(db_conn)
        self._whisper = whisper
        self._translator = translator
        self._probe = probe_fn or _probe_metadata
        self._download = download_fn or _download_audio

    def run(self, job_id: str) -> None:
        """Execute the full pipeline for job_id.

        Advances progress monotonically. Sets job to completed or failed.
        Audio file is deleted unconditionally (success and failure).
        """
        job = self._jobs.get(job_id)
        if job is None:
            logger.error("Pipeline.run: job %s not found", job_id)
            return

        audio_path: Optional[Path] = None

        try:
            self._jobs.update_status(job_id, "processing")

            # Stage 1: probe metadata → 5%
            video_id = job["video_id"]
            url = f"https://www.youtube.com/watch?v={video_id}"
            meta = self._probe(url)
            # Update video_id from probe result (may differ if URL resolves differently)
            video_id = meta.video_id
            self._jobs.update_progress(job_id, 5)

            # Stage 2: download audio → 15%
            audio_path = self._download(video_id)
            self._jobs.update_progress(job_id, 15)

            # Stage 3: whisper transcription → 45%
            words = self._whisper.transcribe(audio_path)
            self._jobs.update_progress(job_id, 45)

            # Stage 4: segmentation → 90%
            segments = _segment(words)
            self._jobs.update_progress(job_id, 90)

            # Stage 5: translation → 95% (results held in memory)
            texts_en = [s["text_en"] for s in segments]
            texts_zh = self._translator.translate_batch(texts_en)
            for i, seg in enumerate(segments):
                seg["text_zh"] = texts_zh[i] if i < len(texts_zh) else ""
            self._jobs.update_progress(job_id, 95)

            # Stage 6: atomic publish → 100%
            self._videos.publish_video(
                video_id=video_id,
                title=meta.title,
                duration_sec=meta.duration_sec,
                source=meta.source,
                segments=segments,
            )
            self._jobs.update_progress(job_id, 100)
            self._jobs.update_status(job_id, "completed")

        except PipelineError as exc:
            logger.warning("Pipeline failed [%s]: %s", exc.error_code, exc.message)
            self._jobs.update_status(
                job_id, "failed",
                error_code=exc.error_code,
                error_message=exc.message,
            )

        except ValueError as exc:
            # segmenter raises ValueError for empty word list
            msg = str(exc)
            logger.warning("Pipeline whisper/segment error: %s", msg)
            self._jobs.update_status(
                job_id, "failed",
                error_code="WHISPER_ERROR",
                error_message=msg,
            )

        except Exception as exc:
            logger.exception("Pipeline internal error for job %s", job_id)
            self._jobs.update_status(
                job_id, "failed",
                error_code="INTERNAL_ERROR",
                error_message=str(exc),
            )

        finally:
            if audio_path is not None and audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    logger.warning("Failed to delete audio: %s", audio_path)


# ---------------------------------------------------------------------------
# Module-level run (used by runner / backward compat)
# ---------------------------------------------------------------------------

def run(job_id: str) -> None:
    """Run pipeline using real clients from environment.

    The runner should prefer Pipeline(...).run(job_id) with injected clients.
    """
    from app.db.connection import get_connection
    from app.services.transcription.whisper import WhisperClient
    from app.services.translation.translator import Translator

    conn = get_connection()
    pipeline = Pipeline(
        db_conn=conn,
        whisper=WhisperClient(),
        translator=Translator(),
    )
    pipeline.run(job_id)
