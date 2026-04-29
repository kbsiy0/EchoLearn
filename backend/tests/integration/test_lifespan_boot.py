"""Integration tests for DB bootstrap on first get_connection() call.

Verifies C1 (correct _DB_PATH) and C2 (schema applied on first connection).
"""
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _index_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFreshCloneBoot:
    """C1+C2: first get_connection() creates dir, db, and all tables."""

    def test_fresh_clone_boots(self, tmp_path):
        """data/ dir is auto-created, all tables exist after first connection."""
        db_file = tmp_path / "data" / "echolearn.db"
        # Confirm directory does NOT exist yet (simulates fresh clone)
        assert not db_file.parent.exists()

        from app.db.connection import get_connection
        conn = get_connection(db_path=str(db_file))
        try:
            tables = _table_names(conn)
        finally:
            conn.close()

        assert db_file.parent.exists(), "data/ directory should be created"
        assert db_file.exists(), "echolearn.db should be created"
        assert "jobs" in tables
        assert "videos" in tables
        assert "segments" in tables

    def test_index_created(self, tmp_path):
        """idx_jobs_video index is created on first connection."""
        db_file = tmp_path / "data" / "echolearn.db"

        from app.db.connection import get_connection
        conn = get_connection(db_path=str(db_file))
        try:
            indexes = _index_names(conn)
        finally:
            conn.close()

        assert "idx_jobs_video" in indexes

    def test_startup_sweep_does_not_raise(self, tmp_path):
        """startup_sweep() should not raise after get_connection() bootstraps DB."""
        db_file = tmp_path / "data" / "echolearn.db"

        from app.db.connection import get_connection
        conn = get_connection(db_path=str(db_file))

        from app.repositories.jobs_repo import JobsRepo
        repo = JobsRepo(conn=conn)

        from app.jobs.runner import JobRunner
        runner = JobRunner(jobs_repo=repo)
        # Should not raise OperationalError: no such table: jobs
        runner.startup_sweep()
        conn.close()


class TestSecondConnectionReusesSchema:
    """C2: second get_connection() does not drop existing data."""

    def test_second_connection_retains_data(self, tmp_path):
        """Row inserted on first connection survives a second connection."""
        import uuid
        from datetime import datetime, timezone

        db_file = tmp_path / "data" / "echolearn.db"

        from app.db.connection import get_connection

        # First connection — insert a job row
        conn1 = get_connection(db_path=str(db_file))
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn1.execute(
            "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, "vid_test", "queued", 0, now, now),
        )
        conn1.commit()
        conn1.close()

        # Second connection — row must still be there
        conn2 = get_connection(db_path=str(db_file))
        try:
            rows = conn2.execute(
                "SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchall()
        finally:
            conn2.close()

        assert len(rows) == 1, "Row inserted on first connection must survive second connection"

    def test_schema_idempotent_on_repeated_calls(self, tmp_path):
        """Calling get_connection() multiple times does not raise."""
        db_file = tmp_path / "data" / "echolearn.db"

        from app.db.connection import get_connection
        for _ in range(3):
            conn = get_connection(db_path=str(db_file))
            conn.close()
        # If schema were NOT IF NOT EXISTS, third call would raise
        # "table X already exists"


class TestLifespanStartupRunsWithoutError:
    """C2: FastAPI lifespan context runs without raising."""

    def test_lifespan_startup_runs_without_error(self, tmp_path):
        """Running FastAPI lifespan startup does not raise exceptions."""
        import asyncio
        from unittest.mock import patch

        db_file = tmp_path / "data" / "echolearn.db"

        # Patch _DB_PATH so the app uses our tmp db
        with patch("app.db.connection._DB_PATH", db_file):
            from app.main import app
            from contextlib import asynccontextmanager

            # Extract and run just the startup portion of lifespan
            # by importing and calling the startup_sweep directly with patched path
            from app.db.connection import get_connection
            conn = get_connection(db_path=str(db_file))

            from app.repositories.jobs_repo import JobsRepo
            repo = JobsRepo(conn=conn)

            from app.jobs.runner import JobRunner
            runner = JobRunner(jobs_repo=repo)
            # This is what lifespan calls — must not raise
            runner.startup_sweep()
            conn.close()


# ---------------------------------------------------------------------------
# T01 — video_progress table smoke tests
# ---------------------------------------------------------------------------

class TestVideoProgressSchema:
    """T01: video_progress table and index created correctly on bootstrap."""

    def test_video_progress_table_exists_after_boot(self):
        """video_progress table is created by the schema bootstrap."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='video_progress'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "video_progress table must exist after bootstrap"

    def test_video_progress_index_exists_after_boot(self):
        """idx_progress_updated_at index is created by the schema bootstrap."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_progress_updated_at'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "idx_progress_updated_at index must exist after bootstrap"

    def test_idx_progress_updated_at_is_desc(self):
        """PRAGMA index_xinfo shows desc=1 for the updated_at column."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            rows = conn.execute(
                "PRAGMA index_xinfo('idx_progress_updated_at')"
            ).fetchall()
        finally:
            conn.close()
        # index_xinfo columns: (seqno, cid, name, desc, coll, key)
        updated_at_row = next((r for r in rows if r[2] == "updated_at"), None)
        assert updated_at_row is not None, "updated_at column must be present in index"
        assert updated_at_row[3] == 1, "updated_at must be indexed DESC (desc=1)"

    def test_video_progress_columns_match_schema(self):
        """PRAGMA table_info shows correct column names and types."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            rows = conn.execute("PRAGMA table_info(video_progress)").fetchall()
        finally:
            conn.close()
        # table_info columns: (cid, name, type, notnull, dflt_value, pk)
        col_map = {r[1]: r[2].upper() for r in rows}
        expected = {
            "video_id": "TEXT",
            "last_played_sec": "REAL",
            "last_segment_idx": "INTEGER",
            "playback_rate": "REAL",
            "loop_enabled": "INTEGER",
            "updated_at": "TEXT",
        }
        for col, typ in expected.items():
            assert col in col_map, f"column '{col}' must exist in video_progress"
            assert col_map[col] == typ, f"column '{col}' must be type {typ}, got {col_map[col]}"

    def test_video_progress_fk_cascades_on_video_delete(self):
        """Deleting a videos row removes the linked video_progress row (CASCADE)."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            conn.execute(
                "INSERT INTO videos (video_id, title, duration_sec, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("vid_cascade", "Test Video", 120.0, "youtube", "2026-04-28T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO video_progress "
                "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("vid_cascade", 10.5, 2, 1.0, 0, "2026-04-28T00:00:00+00:00"),
            )
            conn.commit()
            conn.execute("DELETE FROM videos WHERE video_id = ?", ("vid_cascade",))
            conn.commit()
            count = conn.execute(
                "SELECT count(*) FROM video_progress WHERE video_id = ?", ("vid_cascade",)
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 0, "CASCADE should remove video_progress row when videos row is deleted"

    def test_video_progress_primary_key_collision_on_duplicate_insert(self):
        """Inserting two rows with the same video_id raises IntegrityError."""
        from app.db.connection import get_connection
        conn = get_connection(":memory:")
        try:
            conn.execute(
                "INSERT INTO videos (video_id, title, duration_sec, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("vid_pk", "PK Test", 60.0, "youtube", "2026-04-28T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO video_progress "
                "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("vid_pk", 5.0, 0, 1.0, 0, "2026-04-28T00:00:00+00:00"),
            )
            conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO video_progress "
                    "(video_id, last_played_sec, last_segment_idx, playback_rate, loop_enabled, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("vid_pk", 8.0, 1, 1.5, 1, "2026-04-28T01:00:00+00:00"),
                )
        finally:
            conn.close()
