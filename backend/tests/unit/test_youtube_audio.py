"""Unit tests for youtube_audio.py — subprocess invocation correctness."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.transcription.youtube_audio import download_audio, probe_metadata, PipelineError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_success_result(returncode: int = 0):
    result = MagicMock()
    result.returncode = returncode
    result.stderr = ""
    result.stdout = ""
    return result


# ---------------------------------------------------------------------------
# Tests: --extractor-args SABR workaround
# ---------------------------------------------------------------------------

class TestDownloadAudioExtractorArgs:
    """Ensure download_audio() includes the SABR workaround flag in the yt-dlp call."""

    def test_extractor_args_flag_present(self, tmp_path):
        """--extractor-args must appear in the yt-dlp argv."""
        with (
            patch("app.services.transcription.youtube_audio.shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("app.services.transcription.youtube_audio.AUDIO_DIR", tmp_path),
            patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _make_success_result(0)
            download_audio("dQw4w9WgXcQ")

        argv = mock_run.call_args[0][0]
        assert "--extractor-args" in argv, f"--extractor-args not in argv: {argv}"

    def test_extractor_args_value_is_sabr_clients(self, tmp_path):
        """The value immediately after --extractor-args must be the SABR client list."""
        with (
            patch("app.services.transcription.youtube_audio.shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("app.services.transcription.youtube_audio.AUDIO_DIR", tmp_path),
            patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _make_success_result(0)
            download_audio("dQw4w9WgXcQ")

        argv = mock_run.call_args[0][0]
        idx = argv.index("--extractor-args")
        assert argv[idx + 1] == "youtube:player_client=ios,android,web", (
            f"Expected SABR value at argv[{idx + 1}], got: {argv[idx + 1]!r}"
        )

    def test_extractor_args_precedes_url(self, tmp_path):
        """--extractor-args must appear before the URL in the argument list."""
        with (
            patch("app.services.transcription.youtube_audio.shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("app.services.transcription.youtube_audio.AUDIO_DIR", tmp_path),
            patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _make_success_result(0)
            download_audio("dQw4w9WgXcQ")

        argv = mock_run.call_args[0][0]
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert url in argv
        assert argv.index("--extractor-args") < argv.index(url), (
            "--extractor-args must appear before the URL"
        )

    def test_download_returns_mp3_path_on_success(self, tmp_path):
        """download_audio() should return the expected mp3 Path on success."""
        with (
            patch("app.services.transcription.youtube_audio.shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("app.services.transcription.youtube_audio.AUDIO_DIR", tmp_path),
            patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _make_success_result(0)
            result = download_audio("dQw4w9WgXcQ")

        assert result == tmp_path / "dQw4w9WgXcQ.mp3"

    def test_download_raises_on_nonzero_returncode(self, tmp_path):
        """download_audio() should raise PipelineError(FFMPEG_MISSING) on yt-dlp failure."""
        with (
            patch("app.services.transcription.youtube_audio.shutil.which", return_value="/usr/bin/yt-dlp"),
            patch("app.services.transcription.youtube_audio.AUDIO_DIR", tmp_path),
            patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _make_success_result(1)
            mock_run.return_value.stderr = "HTTP 403 Forbidden"
            with pytest.raises(PipelineError) as exc_info:
                download_audio("dQw4w9WgXcQ")

        assert exc_info.value.error_code == "FFMPEG_MISSING"


# ---------------------------------------------------------------------------
# Helpers for probe_metadata tests
# ---------------------------------------------------------------------------

def _make_probe_result(duration_sec: float, returncode: int = 0) -> MagicMock:
    """Return a mock subprocess.CompletedProcess with yt-dlp --dump-json output."""
    result = MagicMock()
    result.returncode = returncode
    result.stderr = ""
    result.stdout = json.dumps({
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "duration": duration_sec,
    })
    return result


# ---------------------------------------------------------------------------
# Tests: probe_metadata MAX_VIDEO_MINUTES guard
# ---------------------------------------------------------------------------

class TestProbeMetadataMaxDuration:
    """Verify probe_metadata enforces MAX_VIDEO_MINUTES boundary."""

    def test_probe_raises_video_too_long_at_21_minutes(self):
        """A video of 21 min 1 sec must raise PipelineError(VIDEO_TOO_LONG)."""
        duration = 21 * 60 + 1  # 1261 seconds
        with patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run:
            mock_run.return_value = _make_probe_result(duration)
            with pytest.raises(PipelineError) as exc_info:
                probe_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert exc_info.value.error_code == "VIDEO_TOO_LONG"

    def test_probe_succeeds_at_20_minutes_exactly(self):
        """A video of exactly 20 min must NOT raise (boundary is inclusive)."""
        duration = 20 * 60  # 1200 seconds
        with patch("app.services.transcription.youtube_audio.subprocess.run") as mock_run:
            mock_run.return_value = _make_probe_result(duration)
            metadata = probe_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert metadata.duration_sec == duration
