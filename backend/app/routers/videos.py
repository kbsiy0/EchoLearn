"""Videos router — GET /api/videos."""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from app.db.connection import get_connection
from app.models.schemas import VideoSummary
from app.repositories.videos_repo import VideosRepo

router = APIRouter(prefix="/api/videos", tags=["videos"])


def get_db_conn() -> sqlite3.Connection:
    return get_connection()


DbConn = Annotated[sqlite3.Connection, Depends(get_db_conn)]


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
