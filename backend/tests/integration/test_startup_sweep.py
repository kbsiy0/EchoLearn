"""Integration tests for JobRunner.startup_sweep().

Covers:
- Stale processing row older than threshold → swept to failed / INTERNAL_ERROR
- Fresh processing row within threshold → left untouched
- Default stale_threshold_sec attribute is 60.0 (no wall-clock wait)
- Audio orphan sweep: mp3 files with no matching processing job are deleted
- Audio orphan sweep: mp3 with a matching processing job is retained
"""

import time
import uuid
from pathlib import Path

import pytest

from app.repositories.jobs_repo import JobsRepo


VIDEO_ID = "dQw4w9WgXcQ"


def _create_processing_job(repo: JobsRepo, video_id: str = VIDEO_ID) -> str:
    job_id = str(uuid.uuid4())
    repo.create(job_id, video_id)
    repo.update_status(job_id, "processing")
    return job_id


class TestStartupSweep:
    def test_stale_processing_row_is_swept(self, db_conn):
        """A processing row older than threshold is swept to failed/INTERNAL_ERROR."""
        from app.jobs.runner import JobRunner

        repo = JobsRepo(db_conn)
        runner = JobRunner(jobs_repo=repo, stale_threshold_sec=0.05)

        job_id = _create_processing_job(repo)
        time.sleep(0.1)  # exceed threshold

        runner.startup_sweep()

        row = repo.get(job_id)
        assert row["status"] == "failed"
        assert row["error_code"] == "INTERNAL_ERROR"
        assert row["error_message"] == "server restarted during processing"

    def test_fresh_processing_row_is_not_swept(self, db_conn):
        """A processing row younger than threshold is left untouched."""
        from app.jobs.runner import JobRunner

        repo = JobsRepo(db_conn)
        runner = JobRunner(jobs_repo=repo, stale_threshold_sec=60.0)

        job_id = _create_processing_job(repo)
        # No sleep — row is fresh

        runner.startup_sweep()

        row = repo.get(job_id)
        assert row["status"] == "processing"

    def test_default_stale_threshold_is_60_seconds(self):
        """JobRunner() with no args has stale_threshold_sec == 60.0."""
        from app.jobs.runner import JobRunner

        runner = JobRunner()
        assert runner.stale_threshold_sec == 60.0


class TestAudioOrphanSweep:
    """Audio files in data/audio/ with no matching processing job are removed."""

    def test_orphan_mp3_no_job_is_deleted(self, db_conn, tmp_path):
        """An mp3 with no DB row at all is removed by startup_sweep."""
        from app.jobs.runner import JobRunner

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        orphan = audio_dir / "orphanAAAAA.mp3"  # 11-char stem
        orphan.write_bytes(b"fake audio")

        repo = JobsRepo(db_conn)
        runner = JobRunner(jobs_repo=repo, audio_dir=audio_dir)
        runner.startup_sweep()

        assert not orphan.exists()

    def test_orphan_mp3_completed_job_is_deleted(self, db_conn, tmp_path):
        """An mp3 whose job is completed (not processing) is removed."""
        from app.jobs.runner import JobRunner

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        video_id = "completedAA"  # exactly 11 chars
        job_id = str(uuid.uuid4())
        repo = JobsRepo(db_conn)
        repo.create(job_id, video_id)
        repo.update_status(job_id, "completed")

        mp3 = audio_dir / f"{video_id}.mp3"
        mp3.write_bytes(b"fake audio")

        runner = JobRunner(jobs_repo=repo, audio_dir=audio_dir)
        runner.startup_sweep()

        assert not mp3.exists()

    def test_active_mp3_processing_job_is_retained(self, db_conn, tmp_path):
        """An mp3 whose job is still processing is kept by startup_sweep."""
        from app.jobs.runner import JobRunner

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        video_id = "activeAAAAA"  # exactly 11 chars
        repo = JobsRepo(db_conn)
        _create_processing_job(repo, video_id=video_id)

        mp3 = audio_dir / f"{video_id}.mp3"
        mp3.write_bytes(b"fake audio")

        runner = JobRunner(jobs_repo=repo, audio_dir=audio_dir)
        runner.startup_sweep()

        assert mp3.exists()

    def test_mixed_files_only_orphans_deleted(self, db_conn, tmp_path):
        """With multiple mp3s, only those without a processing job are removed."""
        from app.jobs.runner import JobRunner

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        active_vid = "activeAAAAA"   # 11 chars
        orphan_vid = "orphanAAAAA"   # 11 chars

        repo = JobsRepo(db_conn)
        _create_processing_job(repo, video_id=active_vid)

        active_mp3 = audio_dir / f"{active_vid}.mp3"
        active_mp3.write_bytes(b"fake audio")
        orphan_mp3 = audio_dir / f"{orphan_vid}.mp3"
        orphan_mp3.write_bytes(b"fake audio")

        runner = JobRunner(jobs_repo=repo, audio_dir=audio_dir)
        runner.startup_sweep()

        assert active_mp3.exists()
        assert not orphan_mp3.exists()
