"""Integration tests for GET /api/videos endpoint."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db.connection import get_connection, get_db_conn
from app.main import app
from app.repositories.videos_repo import VideosRepo


def _make_client(db_conn: sqlite3.Connection) -> TestClient:
    """TestClient with DB overridden to use in-memory connection."""
    def _override_conn() -> sqlite3.Connection:
        return db_conn

    app.dependency_overrides[get_db_conn] = _override_conn
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.pop(get_db_conn, None)


@pytest.fixture()
def client(db_conn: sqlite3.Connection):
    yield from _make_client(db_conn)


def test_list_videos_empty_db(client: TestClient):
    resp = client.get("/api/videos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_videos_returns_rows_after_publish(db_conn: sqlite3.Connection, client: TestClient):
    repo = VideosRepo(db_conn)
    repo.upsert_video_clear_segments(
        video_id="dQw4w9WgXcW",
        title="Rick Astley",
        duration_sec=213.0,
        source="whisper",
    )
    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["video_id"] == "dQw4w9WgXcW"
    assert data[0]["title"] == "Rick Astley"
    assert data[0]["duration_sec"] == 213.0
    assert "created_at" in data[0]


# ---------------------------------------------------------------------------
# T05 — LEFT JOIN + ORDER BY tests
# ---------------------------------------------------------------------------

def _insert_video(conn: sqlite3.Connection, video_id: str, title: str, created_at: str) -> None:
    """Insert a videos row with explicit created_at (bypasses now_iso())."""
    conn.execute(
        "INSERT INTO videos (video_id, title, duration_sec, source, created_at) "
        "VALUES (?, ?, 120.0, 'whisper', ?)",
        (video_id, title, created_at),
    )
    conn.commit()


def _insert_progress(
    conn: sqlite3.Connection,
    video_id: str,
    updated_at: str,
    last_played_sec: float = 10.0,
    last_segment_idx: int = 1,
    playback_rate: float = 1.0,
    loop_enabled: int = 0,
) -> None:
    """Insert a video_progress row with explicit updated_at."""
    conn.execute(
        "INSERT INTO video_progress "
        "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at),
    )
    conn.commit()


def test_list_videos_returns_progress_null_when_never_played(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Single video with no progress row → progress field is null."""
    _insert_video(db_conn, "aaa1111111a", "Alpha", "2026-04-25T10:00:00Z")

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["video_id"] == "aaa1111111a"
    assert data[0]["progress"] is None


def test_list_videos_returns_nested_progress_when_present(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Single video + progress row → nested progress object with all fields."""
    _insert_video(db_conn, "bbb2222222b", "Beta", "2026-04-25T09:00:00Z")
    _insert_progress(
        db_conn, "bbb2222222b", "2026-04-26T08:00:00Z",
        last_played_sec=42.5, last_segment_idx=3, playback_rate=1.5, loop_enabled=0,
    )

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    p = data[0]["progress"]
    assert p is not None
    assert p["last_played_sec"] == 42.5
    assert p["last_segment_idx"] == 3
    assert p["playback_rate"] == 1.5
    assert p["loop_enabled"] is False
    assert p["updated_at"] == "2026-04-26T08:00:00Z"


def test_list_videos_with_progress_first_then_without(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Videos with progress come before videos without progress."""
    # newest created_at but no progress
    _insert_video(db_conn, "aaa1111111a", "Alpha", "2026-04-25T12:00:00Z")
    # older created_at but has progress
    _insert_video(db_conn, "bbb2222222b", "Beta", "2026-04-25T09:00:00Z")
    _insert_progress(db_conn, "bbb2222222b", "2026-04-26T08:00:00Z")
    # older created_at but has progress
    _insert_video(db_conn, "ccc3333333c", "Gamma", "2026-04-25T11:00:00Z")
    _insert_progress(db_conn, "ccc3333333c", "2026-04-25T15:00:00Z")

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # with-progress group first
    assert data[0]["progress"] is not None
    assert data[1]["progress"] is not None
    # without-progress group last
    assert data[2]["progress"] is None
    assert data[2]["video_id"] == "aaa1111111a"


def test_list_videos_with_progress_sorted_by_progress_updated_at_desc(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Within the with-progress group, sort by progress.updated_at DESC."""
    _insert_video(db_conn, "aaa1111111a", "A", "2026-04-25T10:00:00Z")
    _insert_progress(db_conn, "aaa1111111a", "2026-04-26T06:00:00Z")

    _insert_video(db_conn, "bbb2222222b", "B", "2026-04-25T09:00:00Z")
    _insert_progress(db_conn, "bbb2222222b", "2026-04-26T08:00:00Z")  # newest

    _insert_video(db_conn, "ccc3333333c", "C", "2026-04-25T11:00:00Z")
    _insert_progress(db_conn, "ccc3333333c", "2026-04-25T15:00:00Z")  # oldest

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    ids = [d["video_id"] for d in data]
    assert ids == ["bbb2222222b", "aaa1111111a", "ccc3333333c"]


def test_list_videos_without_progress_sorted_by_created_at_desc(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Without-progress group sorts by created_at DESC (Phase 0/1b compatibility)."""
    _insert_video(db_conn, "aaa1111111a", "A", "2026-04-25T10:00:00Z")
    _insert_video(db_conn, "bbb2222222b", "B", "2026-04-25T12:00:00Z")  # newest
    _insert_video(db_conn, "ccc3333333c", "C", "2026-04-25T08:00:00Z")  # oldest

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    ids = [d["video_id"] for d in data]
    assert ids == ["bbb2222222b", "aaa1111111a", "ccc3333333c"]
    # all without progress
    assert all(d["progress"] is None for d in data)


def test_list_videos_three_video_mixed_state_example(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Exact example from design.md §12: Beta → Gamma → Alpha."""
    _insert_video(db_conn, "aaa1111111a", "Video Alpha", "2026-04-25T10:00:00Z")
    # no progress for Alpha

    _insert_video(db_conn, "bbb2222222b", "Video Beta", "2026-04-25T09:00:00Z")
    _insert_progress(db_conn, "bbb2222222b", "2026-04-26T08:00:00Z")

    _insert_video(db_conn, "ccc3333333c", "Video Gamma", "2026-04-25T11:00:00Z")
    _insert_progress(db_conn, "ccc3333333c", "2026-04-25T15:00:00Z")

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert [d["title"] for d in data] == ["Video Beta", "Video Gamma", "Video Alpha"]


def test_list_videos_uses_created_at_as_tiebreak_for_equal_progress_updated_at(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Equal progress.updated_at tiebreaker: videos.created_at DESC (Pi → Qubit)."""
    shared_updated_at = "2026-04-26T08:00:00Z"

    _insert_video(db_conn, "ppp4444444p", "Pi", "2026-04-25T11:00:00Z")   # newer created_at
    _insert_video(db_conn, "qqq5555555q", "Qubit", "2026-04-25T10:00:00Z")  # older created_at

    # Insert with identical updated_at via raw SQL to bypass now_iso() clock
    db_conn.execute(
        "INSERT INTO video_progress "
        "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
        "VALUES (?, 5.0, 0, 1.0, 0, ?)",
        ("ppp4444444p", shared_updated_at),
    )
    db_conn.execute(
        "INSERT INTO video_progress "
        "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
        "VALUES (?, 5.0, 0, 1.0, 0, ?)",
        ("qqq5555555q", shared_updated_at),
    )
    db_conn.commit()

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert [d["title"] for d in data] == ["Pi", "Qubit"]


def test_list_videos_loop_enabled_serialized_as_bool_in_nested_progress(
    db_conn: sqlite3.Connection, client: TestClient
):
    """SQLite stores loop_enabled as 0/1 int; router must convert to JSON bool."""
    _insert_video(db_conn, "bbb2222222b", "Beta", "2026-04-25T09:00:00Z")
    _insert_progress(db_conn, "bbb2222222b", "2026-04-26T08:00:00Z", loop_enabled=1)

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    p = data[0]["progress"]
    assert p is not None
    # JSON true (bool), not integer 1
    assert p["loop_enabled"] is True
    assert type(p["loop_enabled"]) is bool


def test_list_videos_phase0_consumer_byte_compatible_when_no_progress(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Phase 0 consumers relying on flat VideoSummary fields still work when progress=None."""
    _insert_video(db_conn, "dQw4w9WgXcW", "Rick Astley", "2026-04-25T10:00:00Z")

    resp = client.get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    row = data[0]
    # Phase 0 fields intact
    assert row["video_id"] == "dQw4w9WgXcW"
    assert row["title"] == "Rick Astley"
    assert row["duration_sec"] == 120.0
    assert "created_at" in row
    # New field is null — backward-compatible addition
    assert row["progress"] is None
