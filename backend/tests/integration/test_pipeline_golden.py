"""Integration tests — pipeline golden path and progress verification.

Migrated for T06: uses subprocess.run mock (no real ffmpeg) and new repo API.
"""

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
    {"text": "Never", "start": 0.0, "end": 1.0},
    {"text": " gonna", "start": 1.0, "end": 2.0},
    {"text": " give", "start": 2.0, "end": 3.0},
    {"text": " you", "start": 3.0, "end": 4.5},
]


def fake_probe(url: str) -> VideoMetadata:
    return VideoMetadata(
        video_id=VIDEO_ID,
        title="Rick Astley",
        duration_sec=45.0,  # short video → single chunk, no real ffmpeg needed
        source="whisper",
    )


def _make_download(tmp_path: Path):
    audio = tmp_path / f"{VIDEO_ID}.mp3"
    audio.write_bytes(b"fake-audio")

    def fake_download(video_id: str) -> Path:
        return audio

    return fake_download


def _make_pipeline(db_conn, whisper, translator, tmp_path: Path) -> Pipeline:
    return Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=fake_probe,
        download_fn=_make_download(tmp_path),
    )


def _create_job(db_conn, video_id: str = VIDEO_ID) -> str:
    job_id = str(uuid.uuid4())
    JobsRepo(db_conn).create(job_id, video_id)
    return job_id


# ---------------------------------------------------------------------------
# Golden path
# ---------------------------------------------------------------------------

def test_golden_path_completes(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("subprocess.run", MagicMock())
    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={"Never gonna give you": "永遠不會放棄你"})

    job_id = _create_job(db_conn)
    pipeline = _make_pipeline(db_conn, whisper, translator, tmp_path)
    pipeline.run(job_id)

    jobs_repo = JobsRepo(db_conn)
    job = jobs_repo.get(job_id)
    assert job["status"] == "completed"
    assert job["progress"] == 100
    assert job["error_code"] is None


def test_golden_path_videos_row_written(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("subprocess.run", MagicMock())
    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    _make_pipeline(db_conn, whisper, translator, tmp_path).run(job_id)

    videos_repo = VideosRepo(db_conn)
    video = videos_repo.get_video(VIDEO_ID)
    assert video is not None
    assert video["title"] == "Rick Astley"
    assert video["duration_sec"] == 45.0


def test_golden_path_segments_written_in_order(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("subprocess.run", MagicMock())
    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    _make_pipeline(db_conn, whisper, translator, tmp_path).run(job_id)

    segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
    assert len(segments) >= 1
    for i, seg in enumerate(segments):
        assert seg["idx"] == i


def test_golden_path_audio_deleted(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("subprocess.run", MagicMock())
    audio = tmp_path / f"{VIDEO_ID}.mp3"
    audio.write_bytes(b"fake")

    def fake_download(video_id: str) -> Path:
        return audio

    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=fake_probe,
        download_fn=fake_download,
    ).run(job_id)

    assert not audio.exists(), "audio file should be deleted after success"


# ---------------------------------------------------------------------------
# Progress ladder
# ---------------------------------------------------------------------------

def test_progress_reaches_100_on_success(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("subprocess.run", MagicMock())
    whisper = FakeWhisperClient(words=WORDS)
    translator = FakeTranslator(mapping={})

    job_id = _create_job(db_conn)
    _make_pipeline(db_conn, whisper, translator, tmp_path).run(job_id)

    job = JobsRepo(db_conn).get(job_id)
    assert job["progress"] == 100
