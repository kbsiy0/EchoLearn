from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
VIDEO_ID_REGEX = r"^[a-zA-Z0-9_-]{11}$"


def validate_youtube_url(url: str) -> str:
    """Validate a YouTube URL and extract the video ID.

    Args:
        url: The YouTube URL to validate.

    Returns:
        The 11-character video ID.

    Raises:
        ValueError: If the URL is invalid, the host is not allowed,
                    or the video ID cannot be extracted/validated.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("INVALID_URL: Could not parse URL")

    # Ensure scheme is http or https
    if parsed.scheme not in ("http", "https"):
        raise ValueError("INVALID_URL: URL must use http or https scheme")

    host = parsed.hostname
    if host is None or host not in ALLOWED_HOSTS:
        raise ValueError(f"INVALID_URL: Host '{host}' is not an allowed YouTube domain")

    video_id: str | None = None

    if host == "youtu.be":
        # youtu.be/<video_id>
        path = parsed.path.lstrip("/")
        if path:
            video_id = path.split("/")[0]
    else:
        path = parsed.path
        if path.startswith("/watch"):
            # youtube.com/watch?v=<video_id>
            qs = parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list:
                video_id = v_list[0]
        elif path.startswith("/shorts/"):
            # youtube.com/shorts/<video_id>
            video_id = path.split("/shorts/")[1].split("/")[0].split("?")[0]
        elif path.startswith("/embed/"):
            # youtube.com/embed/<video_id>
            video_id = path.split("/embed/")[1].split("/")[0].split("?")[0]
        elif path.startswith("/v/"):
            # youtube.com/v/<video_id>
            video_id = path.split("/v/")[1].split("/")[0].split("?")[0]

    if not video_id:
        raise ValueError("INVALID_URL: Could not extract video ID from URL")

    if not re.match(VIDEO_ID_REGEX, video_id):
        raise ValueError(f"INVALID_URL: Video ID '{video_id}' is not valid")

    return video_id
