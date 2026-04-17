"""Integration tests for JobRunner.submit() — failure handling.

Covers:
- PipelineError(WHISPER_ERROR) → job.status=failed, error_code=WHISPER_ERROR
- Unknown exception → job.status=failed, error_code=INTERNAL_ERROR
- submit() does NOT propagate exceptions to the caller
"""

import uuid

import pytest

from app.jobs.runner import JobRunner
from app.repositories.jobs_repo import JobsRepo
from app.services.transcription.youtube_audio import PipelineError


VIDEO_ID = "dQw4w9WgXcQ"


def _create_job(repo: JobsRepo, video_id: str = VIDEO_ID) -> str:
    job_id = str(uuid.uuid4())
    repo.create(job_id, video_id)
    return job_id


class TestRunnerSubmit:
    def test_pipeline_error_sets_failed_with_error_code(self, db_conn):
        """PipelineError raised inside worker → job failed with correct error_code."""
        repo = JobsRepo(db_conn)
        job_id = _create_job(repo)

        def fail_with_pipeline_error(jid: str) -> None:
            raise PipelineError("WHISPER_ERROR", "transcription failed")

        runner = JobRunner(jobs_repo=repo, pipeline_run_fn=fail_with_pipeline_error)
        runner.submit(job_id)
        runner.shutdown(wait=True)

        row = repo.get(job_id)
        assert row["status"] == "failed"
        assert row["error_code"] == "WHISPER_ERROR"
        assert "transcription failed" in row["error_message"]

    def test_unknown_exception_sets_internal_error(self, db_conn):
        """Any non-PipelineError exception → job failed with INTERNAL_ERROR."""
        repo = JobsRepo(db_conn)
        job_id = _create_job(repo)

        def fail_with_unexpected(jid: str) -> None:
            raise RuntimeError("disk full or something")

        runner = JobRunner(jobs_repo=repo, pipeline_run_fn=fail_with_unexpected)
        runner.submit(job_id)
        runner.shutdown(wait=True)

        row = repo.get(job_id)
        assert row["status"] == "failed"
        assert row["error_code"] == "INTERNAL_ERROR"

    def test_submit_does_not_propagate_exceptions(self, db_conn):
        """submit() itself must not raise even when the pipeline raises."""
        repo = JobsRepo(db_conn)
        job_id = _create_job(repo)

        def always_explode(jid: str) -> None:
            raise RuntimeError("boom")

        runner = JobRunner(jobs_repo=repo, pipeline_run_fn=always_explode)

        # This must not raise
        try:
            runner.submit(job_id)
            runner.shutdown(wait=True)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"submit() propagated an exception: {exc!r}")

    def test_successful_run_does_not_override_status(self, db_conn):
        """When pipeline succeeds, runner does not overwrite any status."""
        repo = JobsRepo(db_conn)
        job_id = _create_job(repo)

        def succeed(jid: str) -> None:
            repo.update_status(jid, "completed")

        runner = JobRunner(jobs_repo=repo, pipeline_run_fn=succeed)
        runner.submit(job_id)
        runner.shutdown(wait=True)

        row = repo.get(job_id)
        assert row["status"] == "completed"
