from __future__ import annotations

import json
import logging
import os
import tempfile

from app.config import settings
from app.models.schemas import SubtitleResponse

logger = logging.getLogger(__name__)


def _cache_path(video_id: str) -> str:
    """Return the cache file path for a given video ID."""
    return os.path.join(settings.CACHE_DIR, f"{video_id}.json")


def get_cached(video_id: str) -> SubtitleResponse | None:
    """Retrieve cached subtitle data for a video.

    Args:
        video_id: The YouTube video ID (already validated).

    Returns:
        SubtitleResponse if cached data exists, None otherwise.
    """
    path = _cache_path(video_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SubtitleResponse(**data)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning(f"Failed to read cache for {video_id}: {e}")
        return None


def save_cache(video_id: str, data: SubtitleResponse) -> None:
    """Save subtitle data to cache using atomic write.

    Uses a temporary file and os.rename for atomic write to prevent
    corrupted cache files from partial writes.

    Args:
        video_id: The YouTube video ID (already validated).
        data: The subtitle response to cache.
    """
    path = _cache_path(video_id)
    cache_dir = os.path.dirname(path)

    os.makedirs(cache_dir, exist_ok=True)

    try:
        # Write to temp file in the same directory, then rename atomically
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data.model_dump(), f, ensure_ascii=False, indent=2)
            os.rename(tmp_path, path)
            logger.info(f"Cached subtitle data for {video_id}")
        except Exception:
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Failed to save cache for {video_id}: {e}")
        raise
