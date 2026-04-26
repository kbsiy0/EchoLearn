"""Videos router — GET /api/videos."""
from __future__ import annotations

from fastapi import APIRouter

from app.db.connection import DbConn
from app.models.schemas import VideoSummary
from app.repositories.videos_repo import VideosRepo

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=list[VideoSummary])
def list_videos(conn: DbConn) -> list[VideoSummary]:
    """Return all videos ordered by created_at DESC."""
    repo = VideosRepo(conn)
    rows = repo.list_videos()
    return [
        VideoSummary(
            video_id=row["video_id"],
            title=row["title"],
            duration_sec=row["duration_sec"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
