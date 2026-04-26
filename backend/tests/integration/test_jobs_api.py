"""Integration tests for POST/GET /api/subtitles/jobs and GET /api/subtitles/{video_id}.

Covers:
- New submission → 201 + job_id + status='queued'
- Dup-submit → same job_id returned for in-flight job
- Cache-hit → synthetic completed job (progress=100), runner.submit NOT called
- Retry after failure → new job_id created
- 404 on unknown job_id
- 404 on /api/subtitles/{video_id} when not yet completed
- HTTP 400 on invalid URL, body has error_code='INVALID_URL'
- error_message does NOT contain stack trace internals
- CORS preserved: OPTIONS /api/videos returns Access-Control-Allow-Origin header
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo


# ---------------------------------------------------------------------------
# Fake runner: tracks submit calls, never runs real pipeline
# ---------------------------------------------------------------------------

class FakeRunner:
    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def startup_sweep(self) -> int:
        return 0

    def shutdown(self, wait: bool = True) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture()
def client(db_conn: sqlite3.Connection, fake_runner: FakeRunner):
    """TestClient with in-memory DB and fake runner injected."""
    import app.routers.jobs as jobs_mod

    def _override_conn() -> sqlite3.Connection:
        return db_conn

    def _override_runner() -> FakeRunner:
        return fake_runner

    app.dependency_overrides[jobs_mod.get_db_conn] = _override_conn
    app.dependency_overrides[jobs_mod.get_runner] = _override_runner

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.pop(jobs_mod.get_db_conn, None)
    app.dependency_overrides.pop(jobs_mod.get_runner, None)


@pytest.fixture()
def subtitles_client(db_conn: sqlite3.Connection):
    """TestClient for /api/subtitles/{video_id} with in-memory DB."""
    import app.routers.subtitles as sub_mod

    def _override_conn() -> sqlite3.Connection:
        return db_conn

    app.dependency_overrides[sub_mod.get_db_conn] = _override_conn

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.pop(sub_mod.get_db_conn, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/subtitles/jobs
# ---------------------------------------------------------------------------

VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcW"
VIDEO_ID = "dQw4w9WgXcW"


def test_new_submission_returns_queued_job(client: TestClient, fake_runner: FakeRunner):
    resp = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert resp.status_code == 201
    data = resp.json()
    assert "job_id" in data
    assert data["video_id"] == VIDEO_ID
    assert data["status"] == "queued"
    assert data["progress"] == 0
    # runner.submit was called once
    assert len(fake_runner.submitted) == 1
    assert fake_runner.submitted[0] == data["job_id"]


def test_dup_submit_returns_same_job(
    client: TestClient, db_conn: sqlite3.Connection, fake_runner: FakeRunner
):
    """Second submit while first job is in-flight returns same job_id."""
    resp1 = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert resp1.status_code == 201
    job_id_1 = resp1.json()["job_id"]

    # Second submit before job completes
    resp2 = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert resp2.status_code == 200
    job_id_2 = resp2.json()["job_id"]

    assert job_id_1 == job_id_2
    # submit called only once (no second dispatch)
    assert len(fake_runner.submitted) == 1


def test_cache_hit_returns_completed_job_without_running_pipeline(
    client: TestClient, db_conn: sqlite3.Connection, fake_runner: FakeRunner
):
    """If a videos row exists, return synthetic completed job without submitting."""
    videos_repo = VideosRepo(db_conn)
    videos_repo.upsert_video_clear_segments(
        video_id=VIDEO_ID,
        title="Rick Astley",
        duration_sec=213.0,
        source="whisper",
    )

    resp = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["progress"] == 100
    assert data["video_id"] == VIDEO_ID
    # runner.submit must NOT have been called
    assert len(fake_runner.submitted) == 0


def test_retry_after_failure_creates_new_job(
    client: TestClient, db_conn: sqlite3.Connection, fake_runner: FakeRunner
):
    """Submitting a URL whose previous job failed creates a fresh job."""
    # Manually insert a failed job
    repo = JobsRepo(db_conn)
    failed_job_id = str(uuid.uuid4())
    repo.create(failed_job_id, VIDEO_ID)
    repo.update_status(failed_job_id, "failed", error_code="INTERNAL_ERROR", error_message="oops")

    resp = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_id"] != failed_job_id
    assert data["status"] == "queued"
    assert len(fake_runner.submitted) == 1


# ---------------------------------------------------------------------------
# Tests: GET /api/subtitles/jobs/{job_id}
# ---------------------------------------------------------------------------

def test_get_job_status_unknown_id(client: TestClient):
    resp = client.get(f"/api/subtitles/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_job_status_returns_job(
    client: TestClient, db_conn: sqlite3.Connection
):
    resp = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    job_id = resp.json()["job_id"]

    resp2 = client.get(f"/api/subtitles/jobs/{job_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["job_id"] == job_id
    assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# Tests: GET /api/subtitles/{video_id}
# ---------------------------------------------------------------------------

def test_get_subtitles_not_found(subtitles_client: TestClient):
    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 404


def test_get_subtitles_returns_data(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    """GET /api/subtitles/{video_id} returns Phase 1b shape after pipeline completes."""
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    job_id = str(uuid.uuid4())
    jobs_repo.create(job_id, VIDEO_ID)
    videos_repo.upsert_video_clear_segments(
        video_id=VIDEO_ID,
        title="Rick Astley",
        duration_sec=213.0,
        source="whisper",
    )
    jobs_repo.update_progress(job_id, 100)
    jobs_repo.update_status(job_id, "completed")

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_id"] == VIDEO_ID
    assert data["title"] == "Rick Astley"
    assert data["status"] == "completed"
    assert data["progress"] == 100
    assert data["segments"] == []


# ---------------------------------------------------------------------------
# Tests: Invalid URL → 400 + INVALID_URL + no stack trace in error_message
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_url", [
    "not-a-url",
    "https://example.com/watch?v=abc123",
    "https://www.youtube.com/",
    "",
    "https://www.youtube.com/watch?v=tooshort",
])
def test_invalid_url_returns_400(client: TestClient, bad_url: str):
    resp = client.post("/api/subtitles/jobs", json={"url": bad_url})
    assert resp.status_code == 400
    data = resp.json()
    assert data["error_code"] == "INVALID_URL"


def test_error_message_has_no_stack_trace(client: TestClient):
    resp = client.post("/api/subtitles/jobs", json={"url": "not-a-url"})
    assert resp.status_code == 400
    msg = resp.json().get("error_message", "")
    # Must not contain stack trace internals
    assert "Traceback" not in msg
    assert 'File "' not in msg
    assert "Error:" not in msg or msg.startswith("INVALID_URL")
    # Must not contain Python class repr patterns like ValueError(
    assert "ValueError" not in msg
    assert "Exception" not in msg


# ---------------------------------------------------------------------------
# Tests: CORS preserved
# ---------------------------------------------------------------------------

def test_cors_preserved():
    """OPTIONS /api/videos returns correct ACAO header for localhost:5173."""
    with TestClient(app) as c:
        resp = c.options(
            "/api/videos",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ---------------------------------------------------------------------------
# Tests: C1/C2 — malformed video_id must return 404 (not 500)
# ---------------------------------------------------------------------------

def test_malformed_video_id_returns_404(subtitles_client: TestClient):
    """video_id shorter than 11 chars triggers repo ValueError — must surface as 404."""
    resp = subtitles_client.get("/api/subtitles/badId")
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("error_code") == "NOT_FOUND"


def test_malformed_video_id_too_long_returns_404(subtitles_client: TestClient):
    """video_id longer than 11 chars triggers repo ValueError — must surface as 404."""
    resp = subtitles_client.get("/api/subtitles/someVideoIdX")
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("error_code") == "NOT_FOUND"


def test_valid_but_unknown_video_id_returns_404(subtitles_client: TestClient):
    """11-char regex-valid video_id not in DB → 404 with same flat body shape."""
    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("error_code") == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: M1 — cache-hit synthetic job must be pollable via GET /jobs/{job_id}
# ---------------------------------------------------------------------------

def test_cache_hit_returns_pollable_job(
    client: TestClient,
    db_conn: sqlite3.Connection,
    fake_runner: FakeRunner,
):
    """POST cache-hit → job_id → GET /jobs/{job_id} must return 200 status=completed."""
    videos_repo = VideosRepo(db_conn)
    videos_repo.upsert_video_clear_segments(
        video_id=VIDEO_ID,
        title="Rick Astley",
        duration_sec=213.0,
        source="whisper",
    )

    # Trigger cache-hit path
    post_resp = client.post("/api/subtitles/jobs", json={"url": VALID_URL})
    assert post_resp.status_code == 200
    job_id = post_resp.json()["job_id"]

    # Poll the returned job_id — must be persisted
    get_resp = client.get(f"/api/subtitles/jobs/{job_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "completed"
    assert data["progress"] == 100
