"""YouTube audio acquisition: metadata probe + audio download.

Public API:
    probe_metadata(url) -> VideoMetadata
        Metadata-only (yt-dlp --dump-json). Does NOT download audio.
        Raises: PipelineError with error_code in {INVALID_URL, VIDEO_UNAVAILABLE, VIDEO_TOO_LONG}

    download_audio(video_id) -> Path
        Downloads audio to data/audio/{video_id}.mp3.
        Validates video_id regex BEFORE composing any Path.
        Raises: PipelineError with error_code=FFMPEG_MISSING
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.config import settings
from app.db._helpers import VIDEO_ID_RE
from app.models.schemas import VideoMetadata
from app.services.errors import ErrorCode

_AUDIO_DIR = Path("data/audio")


class PipelineError(Exception):
    """Raised by pipeline stages with a canonical error_code.

    This is the base exception for all pipeline stage failures.
    Subclasses may be raised by specific stages (WhisperError, TranslationError).
    """

    def __init__(self, error_code: ErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.error_code: ErrorCode | str = error_code
        self.message = message


def probe_metadata(url: str) -> VideoMetadata:
    """Probe YouTube URL for metadata without downloading audio.

    Args:
        url: YouTube URL (e.g. https://www.youtube.com/watch?v=...)

    Returns:
        VideoMetadata with video_id, title, duration_sec, source.

    Raises:
        PipelineError(INVALID_URL): URL cannot be parsed as a YouTube video.
        PipelineError(VIDEO_UNAVAILABLE): private, deleted, or geo-blocked.
        PipelineError(VIDEO_TOO_LONG): duration exceeds MAX_VIDEO_MINUTES.
    """
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", url],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        stderr = result.stderr.lower()
        if any(kw in stderr for kw in ("private", "unavailable", "members only",
                                        "age", "removed", "not available")):
            raise PipelineError(ErrorCode.VIDEO_UNAVAILABLE, f"Video unavailable: {url}")
        raise PipelineError(ErrorCode.INVALID_URL, f"Cannot retrieve metadata for URL: {url}")

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise PipelineError(ErrorCode.INVALID_URL, f"Cannot parse yt-dlp output for: {url}")

    video_id = info.get("id", "")
    if not VIDEO_ID_RE.match(video_id):
        raise PipelineError(ErrorCode.INVALID_URL, f"Unexpected video_id format: {video_id!r}")

    duration_sec = float(info.get("duration", 0))
    if duration_sec / 60 > settings.MAX_VIDEO_MINUTES:
        raise PipelineError(
            ErrorCode.VIDEO_TOO_LONG,
            f"Video is {duration_sec / 60:.1f} min, max is {settings.MAX_VIDEO_MINUTES} min",
        )

    return VideoMetadata(
        video_id=video_id,
        title=info.get("title", ""),
        duration_sec=duration_sec,
        source="whisper",
    )


def download_audio(video_id: str) -> Path:
    """Download YouTube audio to data/audio/{video_id}.mp3.

    Validates video_id regex BEFORE composing any filesystem path.

    Args:
        video_id: 11-character YouTube video ID.

    Returns:
        Path to the downloaded mp3 file.

    Raises:
        PipelineError(INVALID_URL): video_id fails regex check.
        PipelineError(FFMPEG_MISSING): yt-dlp/ffmpeg not available or download failed.
    """
    if not VIDEO_ID_RE.match(video_id):
        raise PipelineError(ErrorCode.INVALID_URL, f"Invalid video_id: {video_id!r}")

    if shutil.which("yt-dlp") is None:
        raise PipelineError(ErrorCode.FFMPEG_MISSING, "yt-dlp is not installed")

    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _AUDIO_DIR / f"{video_id}.mp3"
    url = f"https://www.youtube.com/watch?v={video_id}"

    result = subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--extractor-args", "youtube:player_client=ios,android,web",
            "-o", str(output_path),
            url,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise PipelineError(ErrorCode.FFMPEG_MISSING, f"Audio download failed: {result.stderr[:200]}")

    return output_path
