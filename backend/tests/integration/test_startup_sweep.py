"""Integration tests for JobRunner.startup_sweep().

Covers:
- Stale processing row older than threshold → swept to failed / INTERNAL_ERROR
- Fresh processing row within threshold → left untouched
- Default stale_threshold_sec attribute is 60.0 (no wall-clock wait)
"""

import time
import uuid

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
