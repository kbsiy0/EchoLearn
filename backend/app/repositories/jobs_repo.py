"""Jobs repository — CRUD for the `jobs` table.

All write methods validate `video_id` against the YouTube canonical regex
before issuing any SQL.  Progress is monotonic: never decreases.

Thread safety: progress monotonicity is enforced via SQL-level conditional
UPDATE (WHERE progress <= ?) so SQLite's own locking guarantees atomicity
even across multiple JobsRepo instances sharing the same connection.
Other writes use a per-instance Lock to serialise access on a shared
in-memory connection (unit tests).
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

        Uses a SQL-level conditional UPDATE (WHERE progress <= ?) so the
        monotonicity guarantee holds even when multiple JobsRepo instances
        share the same SQLite connection.

        In strict mode (EL_TEST_STRICT=1): if progress would decrease,
        raises AssertionError *before* issuing any SQL.
        In production mode: a lower value is silently ignored (no-op + WARN).
        """
        strict = os.environ.get("EL_TEST_STRICT") == "1"

        with self._lock:
            current = self._get_unlocked(job_id)
            current_progress = current["progress"] if current else 0

            if progress < current_progress:
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

            # SQL-level conditional UPDATE: only writes if stored progress is
            # still <= the value we intend to set.  Atomicity is guaranteed
            # by SQLite; the lock covers the entire read-decide-write cycle so
            # threads sharing one connection don't interleave transactions.
            cursor = self._conn.execute(
                "UPDATE jobs SET progress=?, updated_at=?"
                " WHERE job_id=? AND progress<=?",
                (progress, _now(), job_id, progress),
            )
            self._conn.commit()

        if cursor.rowcount == 0:
            logger.warning(
                "update_progress conditional no-op (concurrent write beat us): "
                "%s tried %d but DB already has higher value",
                job_id, progress,
            )

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
