from __future__ import annotations

import re
from datetime import datetime, timezone

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def validate_video_id(video_id: str) -> None:
    """Raise ValueError if `video_id` is not the canonical YouTube 11-char form."""
    if not VIDEO_ID_RE.match(video_id):
        raise ValueError(
            f"Invalid video_id {video_id!r}: must match ^[A-Za-z0-9_-]{{11}}$"
        )


def now_iso() -> str:
    """UTC timestamp via `datetime.isoformat()` — preserves microseconds + offset."""
    return datetime.now(timezone.utc).isoformat()
