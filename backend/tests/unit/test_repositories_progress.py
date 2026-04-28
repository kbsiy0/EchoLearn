"""
T02 — ProgressRepo unit tests: get / upsert / delete + validation invariants.

All tests use an in-memory SQLite connection (schema applied via get_connection).
"""

import time

import pytest

VIDEO_ID = "dQw4w9WgXcQ"
VIDEO_ID_2 = "aaaaa_bbbbb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn():
    from app.db.connection import get_connection
    return get_connection(":memory:")


def _make_repo(conn):
    from app.repositories.progress_repo import ProgressRepo
    return ProgressRepo(conn)


def _seed_video(conn, video_id=VIDEO_ID, duration_sec=120.0):
    """Insert a minimal videos row so FK is satisfied."""
    conn.execute(
        "INSERT INTO videos (video_id, title, duration_sec, source, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (video_id, "Test Video", duration_sec, "youtube", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()


def _seed_progress(conn, video_id=VIDEO_ID, last_played_sec=60.0,
                   last_segment_idx=3, playback_rate=1.0, loop_enabled=0):
    """Insert a raw progress row (bypassing FK if needed via PRAGMA)."""
    conn.execute(
        "INSERT INTO video_progress "
        "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled,
         "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get — returns None when no row
# ---------------------------------------------------------------------------

def test_get_returns_none_when_no_row():
    conn = _make_conn()
    repo = _make_repo(conn)
    assert repo.get(VIDEO_ID) is None


# ---------------------------------------------------------------------------
# get — bool conversion
# ---------------------------------------------------------------------------

def test_get_returns_row_with_bool_conversion():
    conn = _make_conn()
    _seed_video(conn)
    _seed_progress(conn, loop_enabled=1)
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert row is not None
    assert row["loop_enabled"] is True


def test_get_returns_row_with_loop_false():
    conn = _make_conn()
    _seed_video(conn)
    _seed_progress(conn, loop_enabled=0)
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert row is not None
    assert row["loop_enabled"] is False


# ---------------------------------------------------------------------------
# get — clamp logic
# ---------------------------------------------------------------------------

def test_get_clamps_last_played_sec_to_videos_duration():
    conn = _make_conn()
    _seed_video(conn, duration_sec=120.0)
    _seed_progress(conn, last_played_sec=200.0)
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert row["last_played_sec"] == 120.0
    # Stored row must be unchanged
    raw = conn.execute(
        "SELECT last_played_sec FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert raw[0] == 200.0


def test_get_does_not_clamp_when_within_bounds():
    conn = _make_conn()
    _seed_video(conn, duration_sec=120.0)
    _seed_progress(conn, last_played_sec=60.0)
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert row["last_played_sec"] == 60.0


def test_get_returns_clamped_value_even_if_videos_row_missing():
    """Orphan progress row (FK disabled for test seed) — must not crash."""
    conn = _make_conn()
    # Disable FK to allow orphan insert
    conn.execute("PRAGMA foreign_keys=OFF")
    _seed_progress(conn, last_played_sec=99.0)
    conn.execute("PRAGMA foreign_keys=ON")
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert row is not None
    assert row["last_played_sec"] == 99.0


# ---------------------------------------------------------------------------
# get — includes updated_at
# ---------------------------------------------------------------------------

def test_get_includes_updated_at():
    conn = _make_conn()
    _seed_video(conn)
    _seed_progress(conn)
    repo = _make_repo(conn)
    row = repo.get(VIDEO_ID)
    assert "updated_at" in row
    assert row["updated_at"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# upsert — first-time insert
# ---------------------------------------------------------------------------

def test_upsert_first_time_inserts_row():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    repo.upsert(VIDEO_ID, last_played_sec=30.0, last_segment_idx=2,
                playback_rate=1.0, loop_enabled=False)
    raw = conn.execute(
        "SELECT * FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert raw is not None
    assert raw["last_played_sec"] == 30.0
    assert raw["last_segment_idx"] == 2
    assert raw["playback_rate"] == 1.0


def test_upsert_existing_row_updates_in_place():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    repo.upsert(VIDEO_ID, last_played_sec=10.0, last_segment_idx=1,
                playback_rate=1.0, loop_enabled=False)
    repo.upsert(VIDEO_ID, last_played_sec=50.0, last_segment_idx=5,
                playback_rate=1.5, loop_enabled=True)
    raw = conn.execute(
        "SELECT * FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()
    assert raw["last_played_sec"] == 50.0
    assert raw["last_segment_idx"] == 5
    assert raw["playback_rate"] == 1.5
    # Only one row should exist
    count = conn.execute(
        "SELECT COUNT(*) FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    assert count == 1


def test_upsert_stamps_updated_at_on_every_call():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    repo.upsert(VIDEO_ID, last_played_sec=10.0, last_segment_idx=1,
                playback_rate=1.0, loop_enabled=False)
    ts1 = conn.execute(
        "SELECT updated_at FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    time.sleep(0.001)
    repo.upsert(VIDEO_ID, last_played_sec=20.0, last_segment_idx=2,
                playback_rate=1.0, loop_enabled=False)
    ts2 = conn.execute(
        "SELECT updated_at FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    assert ts2 > ts1


# ---------------------------------------------------------------------------
# upsert — validation: numeric ranges
# ---------------------------------------------------------------------------

def test_upsert_rejects_negative_last_played_sec():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    with pytest.raises(ValueError, match="last_played_sec"):
        repo.upsert(VIDEO_ID, last_played_sec=-0.1, last_segment_idx=0,
                    playback_rate=1.0, loop_enabled=False)


def test_upsert_rejects_negative_segment_idx():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    with pytest.raises(ValueError, match="last_segment_idx"):
        repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=-1,
                    playback_rate=1.0, loop_enabled=False)


def test_upsert_rejects_rate_below_0_5():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    with pytest.raises(ValueError, match="playback_rate"):
        repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                    playback_rate=0.49, loop_enabled=False)


def test_upsert_rejects_rate_above_2_0():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    with pytest.raises(ValueError, match="playback_rate"):
        repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                    playback_rate=2.01, loop_enabled=False)


def test_upsert_accepts_rate_at_exact_bounds():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    # Should not raise
    repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                playback_rate=0.5, loop_enabled=False)
    repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                playback_rate=2.0, loop_enabled=False)


# ---------------------------------------------------------------------------
# upsert — validation: video_id format
# ---------------------------------------------------------------------------

def test_upsert_validates_video_id_via_shared_helper():
    conn = _make_conn()
    repo = _make_repo(conn)
    with pytest.raises(ValueError):
        repo.upsert("abc", last_played_sec=0.0, last_segment_idx=0,
                    playback_rate=1.0, loop_enabled=False)


# ---------------------------------------------------------------------------
# upsert — loop_enabled stored as INTEGER
# ---------------------------------------------------------------------------

def test_upsert_writes_loop_enabled_as_integer_under_the_hood():
    conn = _make_conn()
    _seed_video(conn)
    repo = _make_repo(conn)
    repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                playback_rate=1.0, loop_enabled=True)
    raw_val = conn.execute(
        "SELECT loop_enabled FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    assert raw_val == 1

    repo.upsert(VIDEO_ID, last_played_sec=0.0, last_segment_idx=0,
                playback_rate=1.0, loop_enabled=False)
    raw_val = conn.execute(
        "SELECT loop_enabled FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    assert raw_val == 0


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_delete_removes_existing_row():
    conn = _make_conn()
    _seed_video(conn)
    _seed_progress(conn)
    repo = _make_repo(conn)
    repo.delete(VIDEO_ID)
    count = conn.execute(
        "SELECT COUNT(*) FROM video_progress WHERE video_id=?", (VIDEO_ID,)
    ).fetchone()[0]
    assert count == 0


def test_delete_idempotent_on_missing_row():
    conn = _make_conn()
    repo = _make_repo(conn)
    result = repo.delete(VIDEO_ID)
    assert result is None  # no exception


def test_delete_does_not_touch_other_rows():
    conn = _make_conn()
    _seed_video(conn, video_id=VIDEO_ID)
    _seed_video(conn, video_id=VIDEO_ID_2)
    _seed_progress(conn, video_id=VIDEO_ID)
    _seed_progress(conn, video_id=VIDEO_ID_2)
    repo = _make_repo(conn)
    repo.delete(VIDEO_ID)
    count = conn.execute(
        "SELECT COUNT(*) FROM video_progress WHERE video_id=?", (VIDEO_ID_2,)
    ).fetchone()[0]
    assert count == 1


def test_delete_validates_video_id():
    conn = _make_conn()
    repo = _make_repo(conn)
    with pytest.raises(ValueError):
        repo.delete("bad-id")
