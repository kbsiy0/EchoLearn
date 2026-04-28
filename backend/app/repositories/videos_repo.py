"""Videos repository — CRUD for `videos` and `segments` tables."""

import json
import sqlite3
from typing import Optional

from ..db._helpers import validate_video_id, now_iso


class VideosRepo:
    """Repository for `videos` and `segments` tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_video_clear_segments(
        self,
        video_id: str,
        title: str,
        duration_sec: float,
        source: str,
    ) -> None:
        """Called once per pipeline run, after probe, before any chunk runs.

        Atomically:
          1. Upsert videos row (title/duration/source).
          2. DELETE FROM segments WHERE video_id=? (clean reprocess).

        This resets partial state so a re-submit for the same video_id wipes
        stale segments before new chunks start appending.
        """
        validate_video_id(video_id)
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO videos (video_id, title, duration_sec, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title,
                    duration_sec=excluded.duration_sec,
                    source=excluded.source,
                    created_at=excluded.created_at
                """,
                (video_id, title, duration_sec, source, now),
            )
            self._conn.execute(
                "DELETE FROM segments WHERE video_id=?", (video_id,)
            )

    def append_segments(self, video_id: str, segments: list[dict]) -> None:
        """Called once per successful chunk to append rows atomically.

        Caller is responsible for assigning monotone idx values that do not
        collide with already-appended segments. Raises on idx collision
        (enforced by PK (video_id, idx)).
        """
        validate_video_id(video_id)
        rows = [
            (
                video_id,
                seg["idx"],
                seg["start"],
                seg["end"],
                seg["text_en"],
                seg["text_zh"],
                json.dumps(seg.get("words", [])),
            )
            for seg in segments
        ]
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO segments
                    (video_id, idx, start_sec, end_sec, text_en, text_zh, words_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_video_view(self, video_id: str) -> Optional[dict]:
        """Aggregate read: latest job + videos row + all segments.

        Returns None if no job for video_id was ever submitted.
        Otherwise returns a dict whose outer keys align exactly with
        SubtitleResponse pydantic field names, so the router body reduces
        to SubtitleResponse(**view). Inner segments list holds ORM dicts.

        Wraps the three SELECTs in BEGIN DEFERRED / COMMIT so WAL-mode
        concurrency cannot tear the snapshot across the three tables.
        """
        validate_video_id(video_id)
        self._conn.execute("BEGIN DEFERRED")
        try:
            job_row = self._conn.execute(
                "SELECT * FROM jobs WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
                (video_id,),
            ).fetchone()

            video_row = self._conn.execute(
                "SELECT * FROM videos WHERE video_id=?",
                (video_id,),
            ).fetchone()

            segment_rows = self._conn.execute(
                "SELECT * FROM segments WHERE video_id=? ORDER BY idx ASC",
                (video_id,),
            ).fetchall()

            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        if job_row is None:
            return None

        return _assemble_view(job_row, video_row, segment_rows)

    def get_video(self, video_id: str) -> Optional[sqlite3.Row]:
        """Return the videos row or None."""
        validate_video_id(video_id)
        cursor = self._conn.execute(
            "SELECT * FROM videos WHERE video_id=?", (video_id,)
        )
        return cursor.fetchone()

    def list_videos(self) -> list[dict]:
        """Return all videos with optional progress, sorted per design.md §12.

        Uses a LEFT JOIN so videos with no progress row still appear.
        Three-clause ORDER BY:
          1. (p.updated_at IS NULL) ASC  → has-progress group (0) before no-progress group (1)
          2. p.updated_at DESC           → most-recently-played first within has-progress group
          3. v.created_at DESC           → newest-created first within no-progress group
                                           (also serves as tiebreaker for equal updated_at)

        Returns list[dict] — each dict carries both videos columns and the
        joined progress columns (prefixed; None when no progress row exists).
        The router is responsible for shaping into Pydantic models.
        """
        cursor = self._conn.execute(
            """
            SELECT v.video_id, v.title, v.duration_sec, v.source, v.created_at,
                   p.last_played_sec, p.last_segment_idx, p.playback_rate,
                   p.loop_enabled, p.updated_at AS progress_updated_at
            FROM videos v
            LEFT JOIN video_progress p USING (video_id)
            ORDER BY (p.updated_at IS NULL) ASC,
                     p.updated_at DESC,
                     v.created_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_segments(self, video_id: str) -> list:
        """Return segments for video_id ordered by idx ASC."""
        validate_video_id(video_id)
        cursor = self._conn.execute(
            "SELECT * FROM segments WHERE video_id=? ORDER BY idx ASC",
            (video_id,),
        )
        return cursor.fetchall()


def _assemble_view(job_row, video_row, segment_rows) -> dict:
    """Build the get_video_view result dict from ORM rows.

    Outer keys match SubtitleResponse field names; inner segments use ORM keys
    (start_sec, end_sec, words_json) for the router to convert to Segment pydantic.
    """
    return {
        "video_id": job_row["video_id"],
        "status": job_row["status"],
        "progress": job_row["progress"],
        "title": video_row["title"] if video_row else None,
        "duration_sec": video_row["duration_sec"] if video_row else None,
        "segments": [dict(r) for r in segment_rows],
        "error_code": job_row["error_code"],
        "error_message": job_row["error_message"],
    }
