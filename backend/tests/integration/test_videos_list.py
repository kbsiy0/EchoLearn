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
