"""Progress router — GET/PUT/DELETE /api/videos/{video_id}/progress."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from app.db.connection import DbConn
from app.db._helpers import validate_video_id
from app.models.schemas import VideoProgress, VideoProgressIn
from app.repositories.progress_repo import ProgressRepo
from app.services.errors import ErrorCode, http_error

router = APIRouter(prefix="/api/videos", tags=["progress"])


def _resolve_video_id(video_id: str) -> None:
    """Raise HTTPException 404 if video_id fails regex validation."""
    try:
        validate_video_id(video_id)
    except ValueError:
        raise http_error(404, ErrorCode.NOT_FOUND, "invalid video_id")


def _parse_body(raw: dict) -> VideoProgressIn:
    """Parse PUT body; convert Pydantic ValidationError → HTTPException 400."""
    try:
        return VideoProgressIn(**raw)
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = err.get("loc", ())
        msg = f"{'.'.join(str(p) for p in loc)}: {err['msg']}" if loc else err["msg"]
        raise http_error(400, ErrorCode.VALIDATION_ERROR, msg)


@router.get("/{video_id}/progress")
def get_progress(video_id: str, conn: DbConn) -> VideoProgress:
    _resolve_video_id(video_id)
    row = ProgressRepo(conn).get(video_id)
    if row is None:
        raise http_error(404, ErrorCode.NOT_FOUND, "progress not found")
    return VideoProgress(**row)


@router.put("/{video_id}/progress", status_code=204)
async def put_progress(video_id: str, request: Request, conn: DbConn) -> Response:
    _resolve_video_id(video_id)
    body = _parse_body(await request.json())
    try:
        ProgressRepo(conn).upsert(
            video_id,
            last_played_sec=body.last_played_sec,
            last_segment_idx=body.last_segment_idx,
            playback_rate=body.playback_rate,
            loop_enabled=body.loop_enabled,
        )
    except sqlite3.IntegrityError:
        raise http_error(404, ErrorCode.NOT_FOUND, "video not found")
    except ValueError as exc:
        raise http_error(400, ErrorCode.VALIDATION_ERROR, str(exc))
    return Response(status_code=204)


@router.delete("/{video_id}/progress", status_code=204)
def delete_progress(video_id: str, conn: DbConn) -> Response:
    _resolve_video_id(video_id)
    ProgressRepo(conn).delete(video_id)
    return Response(status_code=204)
