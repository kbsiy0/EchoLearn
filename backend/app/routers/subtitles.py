"""Subtitles router — GET /api/subtitles/{video_id}.

Replaces the old monolithic subtitles.py (T05). All job-creation logic
has moved to routers/jobs.py; video listing has moved to routers/videos.py.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.connection import get_connection
from app.models.schemas import Segment, SubtitleResponse, WordTiming
from app.repositories.videos_repo import VideosRepo

router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])


def get_db_conn() -> sqlite3.Connection:
    return get_connection()


DbConn = Annotated[sqlite3.Connection, Depends(get_db_conn)]


@router.get("/{video_id}", response_model=SubtitleResponse)
def get_subtitles(video_id: str, conn: DbConn) -> SubtitleResponse:
    """Return subtitle data for a completed video."""
    repo = VideosRepo(conn)
    try:
        video_row = repo.get_video(video_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "subtitle not found"},
        )
    if video_row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "subtitle not found"},
        )

    segment_rows = repo.get_segments(video_id)
    segments = [
        Segment(
            idx=row["idx"],
            start=row["start_sec"],
            end=row["end_sec"],
            text_en=row["text_en"],
            text_zh=row["text_zh"],
            words=[WordTiming(**w) for w in json.loads(row["words_json"] or "[]")],
        )
        for row in segment_rows
    ]

    return SubtitleResponse(
        video_id=video_row["video_id"],
        title=video_row["title"],
        duration_sec=video_row["duration_sec"],
        segments=segments,
    )
