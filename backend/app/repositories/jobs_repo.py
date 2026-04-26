"""Jobs repository — CRUD for the `jobs` table.

Thread safety: all writes share a per-connection Lock so concurrent
JobsRepo instances on the same connection serialise correctly.
Progress monotonicity is additionally enforced by SQL WHERE progress<=?.
"""

import logging
import os
import re
import sqlite3
import threading
import weakref
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# id(conn) → Lock mapping.  A finalizer removes entries when connections close.
_conn_locks: dict = {}
_conn_locks_guard = threading.Lock()


def _lock_for(conn: sqlite3.Connection) -> threading.Lock:
    conn_id = id(conn)
    with _conn_locks_guard:
        if conn_id not in _conn_locks:
            lock = threading.Lock()
            _conn_locks[conn_id] = lock

            def _cleanup(cid: int = conn_id) -> None:
                with _conn_locks_guard:
                    _conn_locks.pop(cid, None)

            try:
                weakref.finalize(conn, _cleanup)
            except TypeError:
                pass  # tolerate: dict stays bounded to open connections

        return _conn_locks[conn_id]


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
        self._lock: threading.Lock = _lock_for(conn)

    def create(self, job_id: str, video_id: str) -> None:
        """Insert a new job row with status='queued' and progress=0."""
        _validate_video_id(video_id)
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)"
                " VALUES (?, ?, 'queued', 0, ?, ?)",
                (job_id, video_id, now, now),
            )
            self._conn.commit()

    def create_completed(self, job_id: str, video_id: str) -> None:
        """Insert a synthetic completed row in one write (cache-hit path)."""
        _validate_video_id(video_id)
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)"
                " VALUES (?, ?, 'completed', 100, ?, ?)",
                (job_id, video_id, now, now),
            )
            self._conn.commit()

    def update_progress(self, job_id: str, progress: int) -> None:
        """Advance progress (monotonic — highest value wins).

        Strict mode (EL_TEST_STRICT=1): raises AssertionError if lowered.
        Production mode: lower write is a silent no-op + WARN log.
        SQL WHERE progress<=? gives cross-instance atomicity.
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

            cursor = self._conn.execute(
                "UPDATE jobs SET progress=?, updated_at=?"
                " WHERE job_id=? AND progress<=?"
                " AND status NOT IN ('failed','completed')",
                (progress, _now(), job_id, progress),
            )
            self._conn.commit()

        if cursor.rowcount == 0:
            logger.warning(
                "update_progress no-op: %s tried %d (rejected by status guard "
                "OR DB already has higher progress)",
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
                "UPDATE jobs SET status=?, error_code=?, error_message=?, updated_at=?"
                " WHERE job_id=?",
                (status, error_code, error_message, _now(), job_id),
            )
            self._conn.commit()

    def sweep_stuck_processing(self, older_than_sec: float) -> int:
        """Flip processing jobs older than threshold to failed/INTERNAL_ERROR.

        Returns the number of rows updated.
        """
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
        ).isoformat()

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

    def get(self, job_id: str) -> Optional[sqlite3.Row]:
        """Return the job row or None if not found."""
        with self._lock:
            return self._get_unlocked(job_id)

    def _get_unlocked(self, job_id: str) -> Optional[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        )
        return cursor.fetchone()

    def find_active_for_video(self, video_id: str) -> Optional[sqlite3.Row]:
        """Return the most recent queued or processing job for video_id, or None."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM jobs WHERE video_id=? AND status IN ('queued','processing')"
                " ORDER BY created_at DESC LIMIT 1",
                (video_id,),
            )
            return cursor.fetchone()

    def get_active_video_ids(self) -> set[str]:
        """Return the set of video_ids with any queued or processing job."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT DISTINCT video_id FROM jobs"
                " WHERE status IN ('queued','processing')"
            )
            return {row["video_id"] for row in cursor.fetchall()}
