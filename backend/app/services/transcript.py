import logging

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)

LANGUAGE_PRIORITY = ["en", "en-US", "en-GB", "en-AU"]


def fetch_transcript(video_id: str) -> tuple[list[dict], str]:
    """Fetch English transcript for a YouTube video.

    Args:
        video_id: The YouTube video ID.

    Returns:
        A tuple of (segments, title) where segments is a list of dicts
        with keys "start", "duration", "text", and title is the video title
        (falls back to video_id if title cannot be determined).

    Raises:
        ValueError: With an error code prefix if the transcript cannot be fetched.
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=LANGUAGE_PRIORITY)
    except TranscriptsDisabled:
        raise ValueError("NO_CAPTIONS: Transcripts are disabled for this video")
    except NoTranscriptFound:
        raise ValueError(
            "NO_CAPTIONS: No English transcript found for this video"
        )
    except VideoUnavailable:
        raise ValueError("VIDEO_PRIVATE: Video is unavailable or private")
    except Exception as e:
        logger.error(f"Unexpected error fetching transcript for {video_id}: {e}")
        raise ValueError(f"NO_CAPTIONS: Failed to fetch transcript: {e}")

    segments = []
    for snippet in transcript.snippets:
        segments.append(
            {
                "start": snippet.start,
                "duration": snippet.duration,
                "text": snippet.text,
            }
        )

    # Use video_id as title fallback since youtube_transcript_api
    # does not provide video title directly
    title = video_id

    return segments, title
