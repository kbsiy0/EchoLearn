"""Integration tests — pipeline failure paths and edge cases."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo
from app.services.pipeline import Pipeline
from app.services.transcription.youtube_audio import PipelineError, VideoMetadata
from tests.fakes.whisper import FakeWhisperClient
from tests.fakes.translator import FakeTranslator


VIDEO_ID = "dQw4w9WgXcQ"
WORDS = [
    {"text": "Hello", "start": 0.0, "end": 1.0},
    {"text": " world", "start": 1.0, "end": 5.0},
]


def _make_audio(tmp_path: Path, video_id: str = VIDEO_ID) -> Path:
    audio = tmp_path / f"{video_id}.mp3"
    audio.write_bytes(b"fake-audio")
    return audio


def _create_job(db_conn, video_id: str = VIDEO_ID) -> str:
    job_id = str(uuid.uuid4())
    JobsRepo(db_conn).create(job_id, video_id)
    return job_id


def _good_probe(url: str) -> VideoMetadata:
    return VideoMetadata(
        video_id=VIDEO_ID, title="Test", duration_sec=60.0, source="whisper"
    )


# ---------------------------------------------------------------------------
# Audio deleted on failure
# ---------------------------------------------------------------------------

def test_audio_deleted_on_whisper_failure(db_conn, tmp_path):
    audio = _make_audio(tmp_path)

    def fake_download(video_id: str) -> Path:
        return audio

    whisper = FakeWhisperClient(words=RuntimeError("API error"))
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=_good_probe,
        download_fn=fake_download,
    ).run(job_id)

    assert not audio.exists(), "audio file must be deleted even on whisper failure"
    job = JobsRepo(db_conn).get(job_id)
    assert job["status"] == "failed"
    assert job["error_code"] == "WHISPER_ERROR"


def test_audio_deleted_on_translation_failure(db_conn, tmp_path):
    audio = _make_audio(tmp_path)

    def fake_download(video_id: str) -> Path:
        return audio

    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(
        mapping=RuntimeError("translation API failed")
    )

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=_good_probe,
        download_fn=fake_download,
    ).run(job_id)

    assert not audio.exists()
    job = JobsRepo(db_conn).get(job_id)
    assert job["status"] == "failed"
    assert job["error_code"] == "TRANSLATION_ERROR"


# ---------------------------------------------------------------------------
# VIDEO_TOO_LONG detected before download
# ---------------------------------------------------------------------------

def test_video_too_long_detected_before_download(db_conn, tmp_path):
    download_called = []

    def fake_probe_too_long(url: str) -> VideoMetadata:
        raise PipelineError("VIDEO_TOO_LONG", "Video too long")

    def fake_download(video_id: str) -> Path:
        download_called.append(video_id)
        return tmp_path / f"{video_id}.mp3"

    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=fake_probe_too_long,
        download_fn=fake_download,
    ).run(job_id)

    assert download_called == [], "download_audio must NOT be called when VIDEO_TOO_LONG"
    job = JobsRepo(db_conn).get(job_id)
    assert job["status"] == "failed"
    assert job["error_code"] == "VIDEO_TOO_LONG"


# ---------------------------------------------------------------------------
# Malformed video_id rejected
# ---------------------------------------------------------------------------

def test_malformed_video_id_rejected(db_conn, tmp_path):
    """video_id that fails regex raises INVALID_URL before any Path composition."""
    from app.services.transcription.youtube_audio import download_audio
    import pytest

    with pytest.raises(PipelineError) as exc_info:
        download_audio("../../../etc/passwd")

    assert exc_info.value.error_code == "INVALID_URL"


# ---------------------------------------------------------------------------
# Whisper empty output → WHISPER_ERROR
# ---------------------------------------------------------------------------

def test_empty_whisper_output_records_whisper_error(db_conn, tmp_path):
    audio = _make_audio(tmp_path)

    def fake_download(video_id: str) -> Path:
        return audio

    whisper = FakeWhisperClient(words=[])  # empty → segmenter raises ValueError

    # FakeWhisperClient returns [] (list), segmenter raises ValueError
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=_good_probe,
        download_fn=fake_download,
    ).run(job_id)

    job = JobsRepo(db_conn).get(job_id)
    assert job["status"] == "failed"
    assert job["error_code"] == "WHISPER_ERROR"
    assert not audio.exists()


# ---------------------------------------------------------------------------
# No videos row if pipeline fails before publish
# ---------------------------------------------------------------------------

def test_no_videos_row_on_early_failure(db_conn, tmp_path):
    def fake_probe_fail(url: str) -> VideoMetadata:
        raise PipelineError("VIDEO_UNAVAILABLE", "private video")

    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=fake_probe_fail,
        download_fn=lambda v: tmp_path / f"{v}.mp3",
    ).run(job_id)

    video = VideosRepo(db_conn).get_video(VIDEO_ID)
    assert video is None, "no videos row should exist if pipeline failed before publish"
