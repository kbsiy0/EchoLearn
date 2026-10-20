"""Videos router — GET /api/videos."""
from __future__ import annotations

from fastapi import APIRouter

from app.db.connection import DbConn
from app.models.schemas import VideoProgress, VideoSummary
from app.repositories.videos_repo import VideosRepo

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _row_to_summary(row: dict) -> VideoSummary:
    """Build VideoSummary from a list_videos() dict row.

    Constructs a nested VideoProgress when progress_updated_at is present.
    Note: last_played_sec is not clamped here — the list page uses it only
    as a ratio display (frontend clamps); clamping lives in GET progress endpoint.
    loop_enabled is cast to bool to satisfy Pydantic and JSON serialisation
    (SQLite stores it as integer 0/1).
    """
    progress = None
    if row["progress_updated_at"] is not None:
        progress = VideoProgress(
            last_played_sec=row["last_played_sec"],
            last_segment_idx=row["last_segment_idx"],
            playback_rate=row["playback_rate"],
            loop_enabled=bool(row["loop_enabled"]),
            updated_at=row["progress_updated_at"],
        )
    return VideoSummary(
        video_id=row["video_id"],
        title=row["title"],
        duration_sec=row["duration_sec"],
        created_at=row["created_at"],
        progress=progress,
    )


@router.get("", response_model=list[VideoSummary])
def list_videos(conn: DbConn) -> list[VideoSummary]:
    """Return all videos ordered by progress recency then creation date."""
    repo = VideosRepo(conn)
    rows = repo.list_videos()
    return [_row_to_summary(row) for row in rows]
