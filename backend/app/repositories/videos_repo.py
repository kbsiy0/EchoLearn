"""Videos repository — CRUD for `videos` and `segments` tables.

publish_video is the ONLY sanctioned write path for making a video observable.
It executes as a single atomic transaction: either both the videos row and all
segments rows are written, or neither is.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _validate_video_id(video_id: str) -> None:
    if not _VIDEO_ID_RE.match(video_id):
        raise ValueError(
            f"Invalid video_id {video_id!r}: must match ^[A-Za-z0-9_-]{{11}}$"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VideosRepo:
    """Repository for `videos` and `segments` tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Atomic publish
    # ------------------------------------------------------------------

    def publish_video(
        self,
        video_id: str,
        title: str,
        duration_sec: float,
        source: str,
        segments: list,
    ) -> None:
        """Atomically upsert the videos row and replace all segment rows.

        Executes in a single SQLite transaction: if any step raises, the
        whole transaction is rolled back — no partial state is observable.

        This is Option A from design.md: the only write path for videos/segments.
        """
        _validate_video_id(video_id)
        now = _now()

        with self._conn:
            # Upsert videos row
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

            # Delete existing segments (clean reprocess)
            self._conn.execute(
                "DELETE FROM segments WHERE video_id=?", (video_id,)
            )

            # Insert all segments — extracted for testability
            self._insert_segments(self._conn, video_id, segments)

    def _insert_segments(
        self,
        conn: sqlite3.Connection,
        video_id: str,
        segments: list,
    ) -> None:
        """Insert segment rows — separated to allow failure injection in tests."""
        rows = [
            (
                video_id,
                seg["idx"],
                seg["start"],
                seg["end"],
                seg["text_en"],
                seg["text_zh"],
                json.dumps(seg["words"]),
            )
            for seg in segments
        ]
        conn.executemany(
            """
            INSERT INTO segments
                (video_id, idx, start_sec, end_sec, text_en, text_zh, words_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_video(self, video_id: str) -> Optional[sqlite3.Row]:
        """Return the videos row or None."""
        _validate_video_id(video_id)
        cursor = self._conn.execute(
            "SELECT * FROM videos WHERE video_id=?", (video_id,)
        )
        return cursor.fetchone()

    def list_videos(self) -> list:
        """Return all videos ordered by created_at DESC."""
        cursor = self._conn.execute(
            "SELECT * FROM videos ORDER BY created_at DESC"
        )
        return cursor.fetchall()

    def get_segments(self, video_id: str) -> list:
        """Return segments for video_id ordered by idx ASC."""
        _validate_video_id(video_id)
        cursor = self._conn.execute(
            "SELECT * FROM segments WHERE video_id=? ORDER BY idx ASC",
            (video_id,),
        )
        return cursor.fetchall()
