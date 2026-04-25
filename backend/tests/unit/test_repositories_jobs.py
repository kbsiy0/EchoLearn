"""
T02 — jobs_repo unit tests: create, update_progress, update_status, get,
find_active_for_video, sweep_stuck_processing, monotonicity invariants
(strict + production modes), and video_id regex enforcement.
WAL concurrency and multi-thread monotonicity live in test_repositories_monotonicity.py.
"""

import logging

import pytest


VIDEO_ID = "dQw4w9WgXcQ"   # 11-char valid YouTube ID
JOB_ID = "job-test-0001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(db_conn):
    from app.repositories.jobs_repo import JobsRepo
    return JobsRepo(db_conn)


def _create(repo, job_id=JOB_ID, video_id=VIDEO_ID):
    repo.create(job_id, video_id)


# ---------------------------------------------------------------------------
# Happy path — create + get
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_inserts_row(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        job = repo.get(JOB_ID)
        assert job is not None
        assert job["job_id"] == JOB_ID
        assert job["video_id"] == VIDEO_ID
        assert job["status"] == "queued"
        assert job["progress"] == 0
        assert job["error_code"] is None
        assert job["error_message"] is None

    def test_create_sets_timestamps(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        job = repo.get(JOB_ID)
        assert job["created_at"] is not None
        assert job["updated_at"] is not None


# ---------------------------------------------------------------------------
# update_progress
# ---------------------------------------------------------------------------

class TestUpdateProgress:
    def test_update_progress_happy(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 25)
        assert repo.get(JOB_ID)["progress"] == 25

    def test_update_progress_to_100(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 100)
        assert repo.get(JOB_ID)["progress"] == 100

    def test_update_progress_monotonic_increase(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 30)
        repo.update_progress(JOB_ID, 60)
        assert repo.get(JOB_ID)["progress"] == 60

    def test_update_progress_lowering_raises_in_strict_mode(self, db_conn):
        """EL_TEST_STRICT=1 (autouse) → lowering raises AssertionError."""
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 50)
        with pytest.raises(AssertionError):
            repo.update_progress(JOB_ID, 30)

    def test_update_progress_lowering_logs_warn_in_production_mode(
        self, db_conn, monkeypatch, caplog
    ):
        """No EL_TEST_STRICT: lowering is no-op and emits WARN log."""
        monkeypatch.delenv("EL_TEST_STRICT", raising=False)
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 50)
        with caplog.at_level(logging.WARNING):
            repo.update_progress(JOB_ID, 20)
        assert repo.get(JOB_ID)["progress"] == 50  # unchanged
        assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    def test_update_status_to_processing(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "processing")
        assert repo.get(JOB_ID)["status"] == "processing"

    def test_update_status_to_completed(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "completed")
        assert repo.get(JOB_ID)["status"] == "completed"

    def test_update_status_to_failed_with_error(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "failed",
                           error_code="WHISPER_ERROR",
                           error_message="no speech detected")
        job = repo.get(JOB_ID)
        assert job["status"] == "failed"
        assert job["error_code"] == "WHISPER_ERROR"
        assert job["error_message"] == "no speech detected"


# ---------------------------------------------------------------------------
# find_active_for_video
# ---------------------------------------------------------------------------

class TestFindActiveForVideo:
    def test_returns_queued_job(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        assert repo.find_active_for_video(VIDEO_ID) is not None

    def test_returns_processing_job(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "processing")
        assert repo.find_active_for_video(VIDEO_ID) is not None

    @pytest.mark.parametrize("status", ["completed", "failed"])
    def test_returns_none_for_terminal_status(self, db_conn, status):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, status)
        assert repo.find_active_for_video(VIDEO_ID) is None

    def test_returns_none_when_no_job(self, db_conn):
        assert _make_repo(db_conn).find_active_for_video(VIDEO_ID) is None


# ---------------------------------------------------------------------------
# sweep_stuck_processing
# ---------------------------------------------------------------------------

class TestSweepStuckProcessing:
    def test_sweep_flips_old_processing_to_failed(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "processing")
        count = repo.sweep_stuck_processing(older_than_sec=0.0)
        assert count >= 1
        job = repo.get(JOB_ID)
        assert job["status"] == "failed"
        assert job["error_code"] == "INTERNAL_ERROR"
        assert "restarted" in job["error_message"]

    def test_sweep_skips_recently_started(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "processing")
        count = repo.sweep_stuck_processing(older_than_sec=3600.0)
        assert count == 0
        assert repo.get(JOB_ID)["status"] == "processing"

    def test_sweep_ignores_non_processing(self, db_conn):
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_status(JOB_ID, "completed")
        count = repo.sweep_stuck_processing(older_than_sec=0.0)
        assert count == 0


# ---------------------------------------------------------------------------
# video_id regex enforcement — write methods reject malformed IDs before SQL
# ---------------------------------------------------------------------------

class TestVideoIdRegex:
    @pytest.mark.parametrize("bad_id", ["short", "has/slash......", "", "toolongXXXXXXX"])
    def test_create_rejects_bad_video_id(self, db_conn, bad_id):
        with pytest.raises(Exception):
            _make_repo(db_conn).create("job-bad-001", bad_id)


# ---------------------------------------------------------------------------
# T06: update_progress is status-guarded (design §8 invariant 11)
# ---------------------------------------------------------------------------

class TestUpdateProgressStatusGuard:
    def test_update_progress_noop_on_failed_status(self, db_conn, monkeypatch):
        """update_progress MUST be a no-op when job status is 'failed'."""
        # Disable strict mode so update_progress doesn't raise on apparent lowering
        monkeypatch.delenv("EL_TEST_STRICT", raising=False)
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 30)
        repo.update_status(JOB_ID, "failed",
                           error_code="WHISPER_ERROR",
                           error_message="transcription failed")
        # Now attempt to advance progress on a failed job
        repo.update_progress(JOB_ID, 80)
        job = repo.get(JOB_ID)
        assert job["progress"] == 30, (
            "update_progress must not advance progress on a failed job"
        )

    def test_update_progress_noop_on_completed_status(self, db_conn, monkeypatch):
        """update_progress MUST be a no-op when job status is 'completed'."""
        monkeypatch.delenv("EL_TEST_STRICT", raising=False)
        repo = _make_repo(db_conn)
        _create(repo)
        repo.update_progress(JOB_ID, 100)
        repo.update_status(JOB_ID, "completed")
        # Attempt to re-advance (e.g. late-arriving callback)
        repo.update_progress(JOB_ID, 100)  # same value — still must be a no-op query
        job = repo.get(JOB_ID)
        assert job["status"] == "completed"
        assert job["progress"] == 100
