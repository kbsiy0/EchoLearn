"""Jobs runner — ThreadPoolExecutor-based async pipeline executor.

Responsibilities:
- submit(job_id): run pipeline.run(job_id) in a worker thread; catch all
  exceptions and write a failed status to DB instead of letting them escape.
- startup_sweep(): mark stale processing rows as failed/INTERNAL_ERROR so
  jobs orphaned by a server crash are never stuck forever.
- shutdown(): gracefully drain in-flight jobs and stop the executor.

Collaborators are injectable via constructor args so tests can use fakes
without touching the real OpenAI API or filesystem.
"""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from app.repositories.jobs_repo import JobsRepo
from app.services.transcription.youtube_audio import PipelineError

logger = logging.getLogger(__name__)

# Type alias for a callable that accepts job_id and runs the pipeline.
PipelineRunFn = Callable[[str], None]


class JobRunner:
    """Wraps a ThreadPoolExecutor to run pipeline jobs asynchronously.

    Args:
        max_workers: Thread pool size (default 2).
        stale_threshold_sec: Jobs in ``processing`` state older than this
            are swept to ``failed`` on startup (default 60.0 seconds).
        jobs_repo: Injectable JobsRepo for unit/integration tests.
            If None, a real repo is constructed from the production DB
            connection on first use (lazy — T05 wiring).
        pipeline_run_fn: Callable(job_id) that executes the pipeline.
            Defaults to the module-level ``pipeline.run`` function.
    """

    def __init__(
        self,
        max_workers: int = 2,
        stale_threshold_sec: float = 60.0,
        jobs_repo: Optional[JobsRepo] = None,
        pipeline_run_fn: Optional[PipelineRunFn] = None,
    ) -> None:
        self.stale_threshold_sec = stale_threshold_sec
        self._max_workers = max_workers
        self._jobs_repo = jobs_repo
        self._pipeline_run_fn = pipeline_run_fn or _default_pipeline_run
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, job_id: str) -> None:
        """Submit job_id to the thread pool for async execution."""
        self._executor.submit(self._run_job, job_id)

    def startup_sweep(self) -> int:
        """Sweep stale processing rows to failed/INTERNAL_ERROR.

        Returns the number of rows swept.
        """
        repo = self._get_repo()
        count = repo.sweep_stuck_processing(
            older_than_sec=self.stale_threshold_sec
        )
        if count:
            logger.warning(
                "startup_sweep: swept %d stale processing job(s) to failed",
                count,
            )
        return count

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool, optionally waiting for in-flight jobs."""
        self._executor.shutdown(wait=wait)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_job(self, job_id: str) -> None:
        """Execute pipeline inside the worker thread; absorb all exceptions."""
        try:
            self._pipeline_run_fn(job_id)
        except PipelineError as exc:
            logger.warning(
                "JobRunner: pipeline error [%s] for job %s: %s",
                exc.error_code, job_id, exc.message,
            )
            self._fail_job(job_id, error_code=exc.error_code, error_message=exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "JobRunner: unexpected error for job %s", job_id
            )
            self._fail_job(
                job_id,
                error_code="INTERNAL_ERROR",
                error_message=str(exc),
            )

    def _fail_job(self, job_id: str, error_code: str, error_message: str) -> None:
        try:
            self._get_repo().update_status(
                job_id, "failed",
                error_code=error_code,
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "JobRunner: could not write failed status for job %s", job_id
            )

    def _get_repo(self) -> JobsRepo:
        if self._jobs_repo is not None:
            return self._jobs_repo
        # Lazy production path (used by T05 router wiring)
        from app.db.connection import get_connection
        return JobsRepo(get_connection())


# ---------------------------------------------------------------------------
# Default pipeline run function (real production path)
# ---------------------------------------------------------------------------

def _default_pipeline_run(job_id: str) -> None:
    """Run the pipeline using real clients from environment."""
    from app.services.pipeline import run as pipeline_run
    pipeline_run(job_id)
