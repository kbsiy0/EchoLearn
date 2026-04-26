"""Pydantic schemas for EchoLearn API."""

from typing import Literal, Optional

from pydantic import BaseModel


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


class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str


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
