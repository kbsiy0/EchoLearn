"""Jobs router — POST /api/subtitles/jobs."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, constr

from app.db.connection import DbConn
from app.models.schemas import JobStatus
from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo
from app.services.errors import ErrorCode, http_error
from app.services.url_validator import validate_youtube_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subtitles", tags=["jobs"])


# ---------------------------------------------------------------------------
# Request schema (strict max-length validation)
# ---------------------------------------------------------------------------

class CreateJobBody(BaseModel):
    url: constr(max_length=2048)  # type: ignore[valid-type]


def get_runner(request: Request) -> Any:
    return request.app.state.runner


Runner = Annotated[Any, Depends(get_runner)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_traceback_tokens(raw: str) -> str:
    """Strip anything that looks like a Python stack trace or exception repr."""
    forbidden = ("Traceback", 'File "', "ValueError", "Exception", "Error(")
    for token in forbidden:
        if token in raw:
            return "Invalid YouTube URL"
    return raw


def _row_to_job_status(row: Any) -> dict:
    return JobStatus(
        job_id=row["job_id"],
        video_id=row["video_id"],
        status=row["status"],
        progress=row["progress"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    ).model_dump()


# ---------------------------------------------------------------------------
# POST /api/subtitles/jobs
# ---------------------------------------------------------------------------

@router.post("/jobs")
def create_job(body: CreateJobBody, conn: DbConn, runner: Runner):
    """Create or return an existing subtitle extraction job."""
    # 1. Validate URL → extract video_id
    try:
        video_id = validate_youtube_url(body.url)
    except ValueError as exc:
        raw_msg = str(exc)
        # Strip "INVALID_URL: " prefix if present
        if raw_msg.startswith("INVALID_URL:"):
            safe_msg = raw_msg[len("INVALID_URL:"):].strip()
        else:
            safe_msg = "Invalid YouTube URL"
        safe_msg = _strip_traceback_tokens(safe_msg)
        raise http_error(400, ErrorCode.INVALID_URL, safe_msg)

    jobs_repo = JobsRepo(conn)
    videos_repo = VideosRepo(conn)

    # 2. Cache hit: video already fully processed → insert synthetic completed job
    video_row = videos_repo.get_video(video_id)
    if video_row is not None:
        synthetic_id = str(uuid.uuid4())
        jobs_repo.create_completed(synthetic_id, video_id)
        return JobStatus(
            job_id=synthetic_id,
            video_id=video_id,
            status="completed",
            progress=100,
            error_code=None,
            error_message=None,
        ).model_dump()

    # 3. Dup-submit: in-flight job exists → return it
    active = jobs_repo.find_active_for_video(video_id)
    if active is not None:
        return _row_to_job_status(active)

    # 4. New job
    job_id = str(uuid.uuid4())
    jobs_repo.create(job_id, video_id)
    runner.submit(job_id)
    logger.info("Created job %s for video %s", job_id, video_id)

    return JSONResponse(
        content=JobStatus(
            job_id=job_id,
            video_id=video_id,
            status="queued",
            progress=0,
            error_code=None,
            error_message=None,
        ).model_dump(),
        status_code=201,
    )


