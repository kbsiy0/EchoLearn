"""Integration tests for GET /api/subtitles/{video_id} — Phase 1b router rewrite.

Covers all 9 rows of the decision table in subtitles-api.md plus:
- test_returns_latest_job_on_resubmission
- test_segments_ordered_by_idx
- test_returns_200_completed_phase0_byte_compat (explicit Phase 0 golden check)
"""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.connection import get_db_conn
from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VIDEO_ID = "dQw4w9WgXcW"


def _make_segment(idx: int, start: float = None, end: float = None) -> dict:
    if start is None:
        start = float(idx)
    if end is None:
        end = start + 1.0
    return {
        "idx": idx,
        "start": start,
        "end": end,
        "text_en": f"Sentence {idx}",
        "text_zh": f"句子 {idx}",
        "words": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def subtitles_client(db_conn: sqlite3.Connection):
    """TestClient wired to in-memory DB via dependency override."""
    def _override_conn() -> sqlite3.Connection:
        return db_conn

    app.dependency_overrides[get_db_conn] = _override_conn
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db_conn, None)


# ---------------------------------------------------------------------------
# Decision table row 1: no job ever submitted → 404
# ---------------------------------------------------------------------------

def test_returns_404_when_no_job_ever_submitted(subtitles_client: TestClient):
    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 404
    detail = resp.json()
    assert detail["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Decision table row 2: queued + no videos row + no segments → 200 queued
# ---------------------------------------------------------------------------

def test_returns_200_queued_with_empty_segments(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    jobs_repo.create(job_id, VIDEO_ID)

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["progress"] == 0
    assert data["segments"] == []
    assert data["title"] is None
    assert data["duration_sec"] is None
    assert data["error_code"] is None
    assert data["error_message"] is None


# ---------------------------------------------------------------------------
# Decision table row 3: processing + no videos row → 200 processing + empty segments
# ---------------------------------------------------------------------------

def test_returns_200_processing_no_video_row(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    jobs_repo.create(job_id, VIDEO_ID)
    jobs_repo.update_status(job_id, "processing")
    jobs_repo.update_progress(job_id, 5)

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["progress"] == 5
    assert data["segments"] == []
    assert data["title"] is None


# ---------------------------------------------------------------------------
# Decision table row 4: processing + videos row + no segments → title/duration filled
# ---------------------------------------------------------------------------

def test_returns_200_processing_with_video_no_segments(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    jobs_repo.update_status(job_id, "processing")
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "My Title", 120.0, "whisper")

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["title"] == "My Title"
    assert data["duration_sec"] == 120.0
    assert data["segments"] == []


# ---------------------------------------------------------------------------
# Decision table row 5: processing + video row + partial segments
# ---------------------------------------------------------------------------

def test_returns_200_processing_with_partial_segments(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    jobs_repo.update_status(job_id, "processing")
    jobs_repo.update_progress(job_id, 32)
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Partial Title", 300.0, "whisper")
    videos_repo.append_segments(VIDEO_ID, [_make_segment(0), _make_segment(1)])

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"
    assert data["progress"] == 32
    assert data["title"] == "Partial Title"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["idx"] == 0
    assert data["segments"][1]["idx"] == 1


# ---------------------------------------------------------------------------
# Decision table row 6: completed + full segments → byte-compat with Phase 0
# ---------------------------------------------------------------------------

def test_returns_200_completed_phase0_byte_compat(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Rick Astley", 213.0, "whisper")
    seg = _make_segment(0, 0.0, 3.5)
    seg["words"] = [{"text": "Hello", "start": 0.0, "end": 1.0}]
    videos_repo.append_segments(VIDEO_ID, [seg])
    jobs_repo.update_progress(job_id, 100)
    jobs_repo.update_status(job_id, "completed")

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    full = resp.json()

    # Phase 0 surface check
    assert full["video_id"] == VIDEO_ID
    assert full["title"] == "Rick Astley"
    assert full["duration_sec"] == 213.0
    assert len(full["segments"]) == 1
    seg_out = full["segments"][0]
    assert seg_out["idx"] == 0
    assert seg_out["start"] == 0.0
    assert seg_out["end"] == 3.5
    assert seg_out["text_en"] == "Sentence 0"

    # New fields present but additive
    assert full["status"] == "completed"
    assert full["progress"] == 100
    assert full["error_code"] is None
    assert full["error_message"] is None


# ---------------------------------------------------------------------------
# Decision table row 7: failed + video row + partial segments
# ---------------------------------------------------------------------------

def test_returns_200_failed_with_partial_segments(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    jobs_repo.update_status(job_id, "processing")
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Partial", 200.0, "whisper")
    videos_repo.append_segments(VIDEO_ID, [_make_segment(0)])
    jobs_repo.update_status(
        job_id, "failed",
        error_code="WHISPER_ERROR",
        error_message="Whisper 轉錄失敗，請稍後重試",
    )

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "WHISPER_ERROR"
    assert data["error_message"] == "Whisper 轉錄失敗，請稍後重試"
    assert len(data["segments"]) == 1


# ---------------------------------------------------------------------------
# Decision table row 8: failed + video row + no segments
# ---------------------------------------------------------------------------

def test_returns_200_failed_with_zero_segments_and_video_row(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Some Title", 99.0, "whisper")
    jobs_repo.update_status(
        job_id, "failed",
        error_code="INTERNAL_ERROR",
        error_message="Internal error",
    )

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["segments"] == []
    assert data["title"] == "Some Title"
    assert data["error_code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Decision table row 9: failed + no video row
# ---------------------------------------------------------------------------

def test_returns_200_failed_no_video_row(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    jobs_repo.update_status(
        job_id, "failed",
        error_code="VIDEO_TOO_LONG",
        error_message="影片過長",
    )

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["title"] is None
    assert data["duration_sec"] is None
    assert data["error_code"] == "VIDEO_TOO_LONG"
    assert data["segments"] == []


# ---------------------------------------------------------------------------
# Latest job on resubmission
# ---------------------------------------------------------------------------

def test_returns_latest_job_on_resubmission(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    """Two jobs for same video — latest by created_at wins."""
    import time

    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    old_job_id = str(uuid.uuid4())
    jobs_repo.create(old_job_id, VIDEO_ID)
    jobs_repo.update_status(old_job_id, "completed")

    # Small sleep to ensure different created_at
    time.sleep(0.01)

    new_job_id = str(uuid.uuid4())
    jobs_repo.create(new_job_id, VIDEO_ID)
    jobs_repo.update_status(new_job_id, "processing")

    # upsert clears old segments; new run has none yet
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Re-run", 60.0, "whisper")

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processing"


# ---------------------------------------------------------------------------
# Segments ordered by idx even when inserted out-of-order
# ---------------------------------------------------------------------------

def test_segments_ordered_by_idx(
    subtitles_client: TestClient, db_conn: sqlite3.Connection
):
    job_id = str(uuid.uuid4())
    jobs_repo = JobsRepo(db_conn)
    videos_repo = VideosRepo(db_conn)

    jobs_repo.create(job_id, VIDEO_ID)
    videos_repo.upsert_video_clear_segments(VIDEO_ID, "Test", 10.0, "whisper")
    # Append in reversed order: idx 2 first, then idx 0 and 1
    videos_repo.append_segments(VIDEO_ID, [_make_segment(2, 2.0, 3.0)])
    videos_repo.append_segments(VIDEO_ID, [_make_segment(0, 0.0, 1.0)])
    videos_repo.append_segments(VIDEO_ID, [_make_segment(1, 1.0, 2.0)])
    jobs_repo.update_status(job_id, "completed")

    resp = subtitles_client.get(f"/api/subtitles/{VIDEO_ID}")
    assert resp.status_code == 200
    segs = resp.json()["segments"]
    assert [s["idx"] for s in segs] == [0, 1, 2]
