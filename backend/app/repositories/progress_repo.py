"""Progress repository — CRUD for `video_progress` table."""

import sqlite3
from typing import Optional

from ..db._helpers import validate_video_id, now_iso


class ProgressRepo:
    """Repository for `video_progress` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, video_id: str) -> Optional[dict]:
        """Return the progress row as a dict (with bool conversion) or None.

        Clamps last_played_sec to videos.duration_sec if greater. The clamp
        is read-side only; the stored row is unchanged.
        """
        validate_video_id(video_id)
        row = self._conn.execute(
            """
            SELECT p.video_id, p.last_played_sec, p.last_segment_idx,
                   p.playback_rate, p.loop_enabled, p.updated_at,
                   v.duration_sec
            FROM video_progress p
            LEFT JOIN videos v ON v.video_id = p.video_id
            WHERE p.video_id = ?
            """,
            (video_id,),
        ).fetchone()

        if row is None:
            return None

        # Server-side clamp invariant: last_played_sec is bounded by the
        # video's duration. Mirrored on the frontend in
        # `useResumeOnce` via `Math.max(0, Math.min(stored, duration))` for
        # defense-in-depth (handles null duration + negative seconds).
        duration_sec = row["duration_sec"]
        stored_sec = row["last_played_sec"]
        clamped_sec = (
            min(stored_sec, duration_sec)
            if duration_sec is not None
            else stored_sec
        )

        return {
            "video_id": row["video_id"],
            "last_played_sec": clamped_sec,
            "last_segment_idx": row["last_segment_idx"],
            "playback_rate": row["playback_rate"],
            "loop_enabled": bool(row["loop_enabled"]),
            "updated_at": row["updated_at"],
        }

    def upsert(
        self,
        video_id: str,
        *,
        last_played_sec: float,
        last_segment_idx: int,
        playback_rate: float,
        loop_enabled: bool,
    ) -> None:
        """Insert-or-update with server-stamped `updated_at`.

        Validates inputs; raises ValueError on violation.
        May raise sqlite3.IntegrityError if videos row is missing (propagates
        to the router for HTTP 404 mapping).
        """
        validate_video_id(video_id)
        _validate_progress_inputs(last_played_sec, last_segment_idx, playback_rate)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO video_progress
                    (video_id, last_played_sec, last_segment_idx,
                     playback_rate, loop_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    last_played_sec  = excluded.last_played_sec,
                    last_segment_idx = excluded.last_segment_idx,
                    playback_rate    = excluded.playback_rate,
                    loop_enabled     = excluded.loop_enabled,
                    updated_at       = excluded.updated_at
                """,
                (
                    video_id,
                    last_played_sec,
                    last_segment_idx,
                    playback_rate,
                    1 if loop_enabled else 0,
                    now_iso(),
                ),
            )

    def delete(self, video_id: str) -> None:
        """Idempotent delete; never raises if no row exists."""
        validate_video_id(video_id)
        with self._conn:
            self._conn.execute(
                "DELETE FROM video_progress WHERE video_id=?", (video_id,)
            )


def _validate_progress_inputs(
    last_played_sec: float,
    last_segment_idx: int,
    playback_rate: float,
) -> None:
    if last_played_sec < 0:
        raise ValueError("last_played_sec must be >= 0")
    if last_segment_idx < 0:
        raise ValueError("last_segment_idx must be >= 0")
    # Range matches the player's ALLOWED_RATES constant in
    # frontend/src/features/player/lib/constants.ts. Tightened from the
    # earlier [0.5, 2.0] forward-compat range — no client ships values
    # outside [0.5, 1.5] and the player physically cannot honor them.
    if not (0.5 <= playback_rate <= 1.5):
        raise ValueError("playback_rate must be in [0.5, 1.5]")
