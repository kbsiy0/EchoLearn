"""Pydantic schemas for EchoLearn API."""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class WordTiming(BaseModel):
    text: str
    start: float
    end: float


class Segment(BaseModel):
    idx: int
    start: float
    end: float
    text_en: str
    text_zh: str
    words: list[WordTiming]


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    source: str


class SubtitleResponse(BaseModel):
    video_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int  # 0..100
    title: Optional[str] = None
    duration_sec: Optional[float] = None
    segments: list[Segment]
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class VideoProgress(BaseModel):
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool
    updated_at: str  # ISO-8601 UTC, server-stamped on every PUT


class VideoProgressIn(BaseModel):
    """PUT body — updated_at is server-stamped and must not be supplied by clients."""

    model_config = ConfigDict(extra="forbid")

    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: Annotated[bool, Field(strict=True)]


class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str
    progress: Optional[VideoProgress] = None  # None when video has never been played


class JobStatus(BaseModel):
    job_id: str
    video_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int  # 0..100
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class CreateJobRequest(BaseModel):
    url: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool
