"""Integration tests for GET/PUT/DELETE /api/videos/{video_id}/progress."""
from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.db.connection import get_db_conn
from app.main import app

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

VIDEO_ID = "dQw4w9WgXcW"   # 11-char valid id
VIDEO_ID_2 = "AbCdEfGhIjK"  # 11-char valid id, second video
INVALID_ID = "abc"           # 3-char — fails regex


def _make_client(db_conn: sqlite3.Connection) -> TestClient:
    def _override() -> sqlite3.Connection:
        return db_conn

    app.dependency_overrides[get_db_conn] = _override
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.pop(get_db_conn, None)


@pytest.fixture()
def client(db_conn: sqlite3.Connection):
    yield from _make_client(db_conn)


def _seed_video(conn: sqlite3.Connection, video_id: str = VIDEO_ID, duration_sec: float = 120.0) -> None:
    conn.execute(
        "INSERT INTO videos (video_id, title, duration_sec, source, created_at) VALUES (?, ?, ?, ?, ?)",
        (video_id, "Test Video", duration_sec, "whisper", "2026-04-25T10:00:00+00:00"),
    )
    conn.commit()


def _seed_progress(
    conn: sqlite3.Connection,
    video_id: str = VIDEO_ID,
    *,
    last_played_sec: float = 60.0,
    last_segment_idx: int = 10,
    playback_rate: float = 1.25,
    loop_enabled: int = 1,
    updated_at: str = "2026-04-25T10:00:00+00:00",
) -> None:
    conn.execute(
        """INSERT INTO video_progress
               (video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at),
    )
    conn.commit()


_VALID_BODY = {
    "last_played_sec": 67.3,
    "last_segment_idx": 17,
    "playback_rate": 1.5,
    "loop_enabled": True,
}

# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_404_when_no_progress_row(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["error_message"] == "progress not found"


def test_get_404_when_video_id_regex_invalid(client: TestClient):
    resp = client.get(f"/api/videos/{INVALID_ID}/progress")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["error_message"] == "invalid video_id"


def test_get_200_returns_progress_shape(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn, duration_sec=180.0)
    _seed_progress(db_conn, last_played_sec=60.0, updated_at="2026-04-25T10:00:00+00:00")
    resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_played_sec"] == 60.0
    assert body["last_segment_idx"] == 10
    assert body["playback_rate"] == 1.25
    assert body["loop_enabled"] is True
    assert body["updated_at"] == "2026-04-25T10:00:00+00:00"


def test_get_clamps_last_played_sec_when_greater_than_duration(
    db_conn: sqlite3.Connection, client: TestClient
):
    _seed_video(db_conn, duration_sec=120.0)
    _seed_progress(db_conn, last_played_sec=200.0)
    resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 200
    assert resp.json()["last_played_sec"] == 120.0
    # underlying row must be unchanged
    raw = db_conn.execute(
        "SELECT last_played_sec FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert raw["last_played_sec"] == 200.0


def test_get_loop_enabled_serialized_as_json_bool_not_int(
    db_conn: sqlite3.Connection, client: TestClient
):
    _seed_video(db_conn)
    _seed_progress(db_conn, loop_enabled=1)
    resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 200
    assert resp.json()["loop_enabled"] is True  # JSON bool, not integer 1


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------


def test_put_204_first_time_creates_row(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(f"/api/videos/{VIDEO_ID}/progress", json=_VALID_BODY)
    assert resp.status_code == 204
    row = db_conn.execute(
        "SELECT * FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert row is not None
    assert row["last_played_sec"] == 67.3
    assert row["last_segment_idx"] == 17
    assert row["playback_rate"] == 1.5
    assert row["loop_enabled"] == 1
    assert row["updated_at"] is not None


def test_put_204_update_overwrites_existing_row(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    _seed_progress(db_conn, last_played_sec=30.0, updated_at="2026-01-01T00:00:00+00:00")
    new_body = {**_VALID_BODY, "last_played_sec": 99.0, "last_segment_idx": 25}
    resp = client.put(f"/api/videos/{VIDEO_ID}/progress", json=new_body)
    assert resp.status_code == 204
    row = db_conn.execute(
        "SELECT * FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert row["last_played_sec"] == 99.0
    assert row["last_segment_idx"] == 25
    assert row["updated_at"] > "2026-01-01T00:00:00+00:00"


def test_put_400_when_rate_below_0_5(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "playback_rate": 0.4}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "playback_rate" in body["error_message"]


def test_put_400_when_rate_above_2_0(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "playback_rate": 2.5}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "playback_rate" in body["error_message"]


def test_put_400_when_last_played_sec_negative(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "last_played_sec": -0.1}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "last_played_sec" in body["error_message"]


def test_put_400_when_last_segment_idx_negative(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "last_segment_idx": -1}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "last_segment_idx" in body["error_message"]


def test_put_400_when_loop_enabled_not_bool(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "loop_enabled": "yes"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "loop_enabled" in body["error_message"]


def test_put_400_when_extra_field_in_body(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    body_with_extra = {**_VALID_BODY, "updated_at": "1970-01-01T00:00:00Z"}
    resp = client.put(f"/api/videos/{VIDEO_ID}/progress", json=body_with_extra)
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    # no row was created
    row = db_conn.execute(
        "SELECT * FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert row is None


def test_put_400_validation_envelope_post_flatten_shape(
    db_conn: sqlite3.Connection, client: TestClient
):
    """Pin the exact top-level shape after main.py flattens detail dict."""
    _seed_video(db_conn)
    resp = client.put(
        f"/api/videos/{VIDEO_ID}/progress", json={**_VALID_BODY, "loop_enabled": "yes"}
    )
    assert resp.status_code == 400
    body = resp.json()
    # post-flatten: error_code and error_message are top-level, NOT nested under "detail"
    assert "error_code" in body
    assert "error_message" in body
    assert "detail" not in body


def test_put_404_when_video_id_does_not_exist_in_videos(client: TestClient):
    """FK violation → 404, no pre-check SELECT."""
    resp = client.put(f"/api/videos/{VIDEO_ID}/progress", json=_VALID_BODY)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["error_message"] == "video not found"


def test_put_404_when_video_id_regex_invalid(client: TestClient):
    resp = client.put(f"/api/videos/{INVALID_ID}/progress", json=_VALID_BODY)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["error_message"] == "invalid video_id"


def test_put_two_back_to_back_last_write_wins(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    body_a = {**_VALID_BODY, "last_played_sec": 10.0, "last_segment_idx": 1}
    body_b = {**_VALID_BODY, "last_played_sec": 99.0, "last_segment_idx": 20}
    r1 = client.put(f"/api/videos/{VIDEO_ID}/progress", json=body_a)
    time.sleep(0.01)  # ensure updated_at advances
    r2 = client.put(f"/api/videos/{VIDEO_ID}/progress", json=body_b)
    assert r1.status_code == 204
    assert r2.status_code == 204
    resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_played_sec"] == 99.0
    assert data["last_segment_idx"] == 20


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_delete_204_when_row_exists(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    _seed_progress(db_conn)
    resp = client.delete(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 204
    # subsequent GET returns 404
    get_resp = client.get(f"/api/videos/{VIDEO_ID}/progress")
    assert get_resp.status_code == 404


def test_delete_204_when_no_row_exists(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    # no progress row
    resp = client.delete(f"/api/videos/{VIDEO_ID}/progress")
    assert resp.status_code == 204  # idempotent


def test_delete_404_when_video_id_regex_invalid(client: TestClient):
    resp = client.delete(f"/api/videos/{INVALID_ID}/progress")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert body["error_message"] == "invalid video_id"


def test_delete_does_not_affect_videos_row(db_conn: sqlite3.Connection, client: TestClient):
    _seed_video(db_conn)
    _seed_progress(db_conn)
    client.delete(f"/api/videos/{VIDEO_ID}/progress")
    row = db_conn.execute("SELECT * FROM videos WHERE video_id=?", (VIDEO_ID,)).fetchone()
    assert row is not None


def test_delete_does_not_affect_other_videos_progress(
    db_conn: sqlite3.Connection, client: TestClient
):
    _seed_video(db_conn, VIDEO_ID)
    _seed_video(db_conn, VIDEO_ID_2)
    _seed_progress(db_conn, VIDEO_ID)
    _seed_progress(db_conn, VIDEO_ID_2, last_played_sec=45.0)
    client.delete(f"/api/videos/{VIDEO_ID}/progress")
    # VIDEO_ID_2 progress should remain
    resp = client.get(f"/api/videos/{VIDEO_ID_2}/progress")
    assert resp.status_code == 200
    assert resp.json()["last_played_sec"] == 45.0
