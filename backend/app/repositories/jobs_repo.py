"""Jobs repository — CRUD for the `jobs` table.

All write methods validate `video_id` against the YouTube canonical regex
before issuing any SQL.  Progress is monotonic: never decreases.

Thread safety: a per-instance Lock serializes writes when multiple threads
share the same connection (e.g., unit tests with in-memory SQLite).
Production code opens one connection per worker thread, so lock contention
is effectively zero in steady state.
"""

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _validate_video_id(video_id: str) -> None:
    if not _VIDEO_ID_RE.match(video_id):
        raise ValueError(
            f"Invalid video_id {video_id!r}: must match ^[A-Za-z0-9_-]{{11}}$"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobsRepo:
    """Repository for the `jobs` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def create(self, job_id: str, video_id: str) -> None:
        """Insert a new job row with status='queued' and progress=0."""
        _validate_video_id(video_id)
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)
                VALUES (?, ?, 'queued', 0, ?, ?)
                """,
                (job_id, video_id, now, now),
            )
            self._conn.commit()

    def update_progress(self, job_id: str, progress: int) -> None:
        """Advance progress — monotonic: highest value wins.

        In strict mode (EL_TEST_STRICT=1): lowering raises AssertionError.
        In production mode: lowering is a no-op and emits a WARN log.

        The read-then-write is protected by a lock so concurrent callers
        on the same connection see a consistent current value.
        """
        with self._lock:
            current = self._get_unlocked(job_id)
            current_progress = current["progress"] if current else 0

            if progress < current_progress:
                strict = os.environ.get("EL_TEST_STRICT") == "1"
                if strict:
                    raise AssertionError(
                        f"update_progress regression: tried to lower {job_id} "
                        f"from {current_progress} to {progress}"
                    )
                logger.warning(
                    "update_progress no-op: tried to lower %s from %d to %d",
                    job_id, current_progress, progress,
                )
                return

            self._conn.execute(
                "UPDATE jobs SET progress=?, updated_at=? WHERE job_id=?",
                (progress, _now(), job_id),
            )
            self._conn.commit()

    def update_status(
        self,
        job_id: str,
        status: Literal["queued", "processing", "completed", "failed"],
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update job status and optionally set error fields."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs
                SET status=?, error_code=?, error_message=?, updated_at=?
                WHERE job_id=?
                """,
                (status, error_code, error_message, _now(), job_id),
            )
            self._conn.commit()

    def sweep_stuck_processing(self, older_than_sec: float) -> int:
        """Flip processing jobs older than threshold to failed with INTERNAL_ERROR.

        Args:
            older_than_sec: Age threshold in seconds.  Jobs whose updated_at
                            timestamp is older than this value are swept.

        Returns:
            Number of rows updated.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
        cutoff_iso = cutoff.isoformat()

        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE jobs
                SET status='failed',
                    error_code='INTERNAL_ERROR',
                    error_message='server restarted during processing',
                    updated_at=?
                WHERE status='processing' AND updated_at < ?
                RETURNING job_id
                """,
                (_now(), cutoff_iso),
            )
            rows = cursor.fetchall()
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> Optional[sqlite3.Row]:
        """Return the job row or None if not found."""
        with self._lock:
            return self._get_unlocked(job_id)

    def _get_unlocked(self, job_id: str) -> Optional[sqlite3.Row]:
        """Read without acquiring lock — caller must hold self._lock."""
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        )
        return cursor.fetchone()

    def find_active_for_video(self, video_id: str) -> Optional[sqlite3.Row]:
        """Return the most recent queued or processing job for video_id, or None."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE video_id=? AND status IN ('queued','processing')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (video_id,),
            )
            return cursor.fetchone()
