from typing import List, Optional

from pydantic import BaseModel


class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class SubtitleSegment(BaseModel):
    index: int
    start: float  # seconds
    end: float
    text_en: str
    text_zh: str
    words: List[WordTiming] = []


class SubtitleResponse(BaseModel):
    video_id: str
    title: str
    segments: List[SubtitleSegment]
    source: str  # "youtube_captions" | "whisper"
    created_at: str  # ISO timestamp


class ErrorResponse(BaseModel):
    code: str  # "INVALID_URL" | "VIDEO_PRIVATE" | "NO_CAPTIONS" | "OPENAI_ERROR" | "VIDEO_TOO_LONG"
    message: str
    retryable: bool


class JobCreate(BaseModel):
    youtube_url: str


class JobStatus(BaseModel):
    job_id: str
    video_id: str
    status: str  # "queued" | "processing" | "completed" | "failed"
    progress: int  # 0-100
    error: Optional[ErrorResponse] = None
    cached: bool = False
