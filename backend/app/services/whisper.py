import logging
import shutil

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


def transcribe_audio(video_id: str, audio_path: str) -> tuple[list[dict], list[dict]]:
    """Transcribe an audio file using OpenAI Whisper API with word-level timestamps.

    Args:
        video_id: The YouTube video ID (for logging).
        audio_path: Path to the audio file to transcribe.

    Returns:
        Tuple of (segments, words):
          - segments: List of dicts with "start", "end", "text"
          - words: List of dicts with "word", "start", "end"

    Raises:
        ValueError: If the Whisper API call fails.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )
    except Exception as e:
        logger.error(f"Whisper transcription failed for {video_id}: {e}")
        raise ValueError(f"OPENAI_ERROR: Whisper transcription failed: {e}")

    segments = []
    for seg in response.segments:
        segments.append(
            {
                "start": seg["start"] if isinstance(seg, dict) else seg.start,
                "end": seg["end"] if isinstance(seg, dict) else seg.end,
                "text": (seg["text"] if isinstance(seg, dict) else seg.text).strip(),
            }
        )

    words = []
    if hasattr(response, "words") and response.words:
        for w in response.words:
            word_text = w["word"] if isinstance(w, dict) else w.word
            word_start = w["start"] if isinstance(w, dict) else w.start
            word_end = w["end"] if isinstance(w, dict) else w.end
            words.append({"word": word_text.strip(), "start": word_start, "end": word_end})

    logger.info(f"Whisper transcribed {len(segments)} segments, {len(words)} words for {video_id}")
    return segments, words


def get_word_timestamps(video_id: str, audio_path: str) -> list[dict]:
    """Get only word-level timestamps from Whisper (for enriching YouTube captions).

    Args:
        video_id: The YouTube video ID (for logging).
        audio_path: Path to the audio file.

    Returns:
        List of dicts with "word", "start", "end".
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
    except Exception as e:
        logger.error(f"Whisper word timestamp failed for {video_id}: {e}")
        raise ValueError(f"OPENAI_ERROR: Whisper word timestamp failed: {e}")

    words = []
    if hasattr(response, "words") and response.words:
        for w in response.words:
            word_text = w["word"] if isinstance(w, dict) else w.word
            word_start = w["start"] if isinstance(w, dict) else w.start
            word_end = w["end"] if isinstance(w, dict) else w.end
            words.append({"word": word_text.strip(), "start": word_start, "end": word_end})

    logger.info(f"Whisper got {len(words)} word timestamps for {video_id}")
    return words
