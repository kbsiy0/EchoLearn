import logging
import os
import subprocess

from app.config import settings

logger = logging.getLogger(__name__)


def download_audio(video_id: str, output_dir: str) -> str:
    """Download audio from a YouTube video using yt-dlp.

    Args:
        video_id: The YouTube video ID.
        output_dir: Directory to save the downloaded audio.

    Returns:
        Path to the downloaded audio file.

    Raises:
        ValueError: If the download fails or the video exceeds the max duration.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = os.path.join(output_dir, f"{video_id}.mp3")

    max_seconds = settings.MAX_VIDEO_MINUTES * 60

    try:
        # First check video duration using yt-dlp
        duration_result = subprocess.run(
            [
                "yt-dlp",
                "--print", "duration",
                "--no-download",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if duration_result.returncode == 0 and duration_result.stdout.strip():
            try:
                duration = float(duration_result.stdout.strip())
                if duration > max_seconds:
                    raise ValueError(
                        f"VIDEO_TOO_LONG: Video is {duration / 60:.0f} minutes, "
                        f"max is {settings.MAX_VIDEO_MINUTES} minutes"
                    )
            except (ValueError, TypeError):
                # If we can't parse duration, proceed anyway
                if "VIDEO_TOO_LONG" in str(duration_result.stdout):
                    raise
                pass

        # Download audio
        result = subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "-o", output_path,
                "--no-playlist",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise ValueError(
                f"VIDEO_PRIVATE: Failed to download audio: {result.stderr.strip()}"
            )

        if not os.path.exists(output_path):
            raise ValueError(
                "VIDEO_PRIVATE: Audio file was not created after download"
            )

        logger.info(f"Downloaded audio for {video_id} to {output_path}")
        return output_path

    except ValueError:
        # Clean up on known errors and re-raise
        if os.path.exists(output_path):
            os.remove(output_path)
        raise
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise ValueError("VIDEO_TOO_LONG: Download timed out, video may be too long")
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        logger.error(f"Failed to download audio for {video_id}: {e}")
        raise ValueError(f"VIDEO_PRIVATE: Failed to download audio: {e}")
