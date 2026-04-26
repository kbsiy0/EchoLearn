"""Subtitles router — GET /api/subtitles/{video_id}."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.db.connection import DbConn
from app.models.schemas import Segment, SubtitleResponse, WordTiming
from app.repositories.videos_repo import VideosRepo

router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])


@router.get("/{video_id}", response_model=SubtitleResponse)
def get_subtitles(video_id: str, conn: DbConn) -> SubtitleResponse:
    """Return live subtitle state for a video at any pipeline stage."""
    repo = VideosRepo(conn)
    try:
        view = repo.get_video_view(video_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "invalid video_id"},
        )
    if view is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "subtitle not found"},
        )

    segments = [
        Segment(
            idx=s["idx"],
            start=s["start_sec"],
            end=s["end_sec"],
            text_en=s["text_en"],
            text_zh=s["text_zh"],
            words=[WordTiming(**w) for w in json.loads(s["words_json"] or "[]")],
        )
        for s in view["segments"]
    ]

    return SubtitleResponse(
        video_id=view["video_id"],
        status=view["status"],
        progress=view["progress"],
        title=view["title"],
        duration_sec=view["duration_sec"],
        segments=segments,
        error_code=view["error_code"],
        error_message=view["error_message"],
    )
