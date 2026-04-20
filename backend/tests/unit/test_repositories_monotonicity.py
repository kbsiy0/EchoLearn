"""
T02 — repository concurrency and monotonicity tests.

1. WAL concurrency: two threads on different job_ids both complete ≤200ms.
2. Progress monotonicity (multi-thread): max value wins.
3. Production mode (no EL_TEST_STRICT): lower write is no-op, higher wins.
"""

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest


VIDEO_ID = "dQw4w9WgXcQ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(db_conn):
    from app.repositories.jobs_repo import JobsRepo
    return JobsRepo(db_conn)


def _make_file_db() -> tuple:
    """Return (conn, db_path) for a real file-based SQLite DB with schema."""
    from app.db.connection import get_connection

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    conn = get_connection(str(db_path))
    schema = (
        Path(__file__).parent.parent.parent / "app" / "db" / "schema.sql"
    ).read_text()
    conn.executescript(schema)
    conn.commit()
    return conn, db_path


# ---------------------------------------------------------------------------
# WAL concurrency: two threads, different job_ids (file-based DB for WAL)
# ---------------------------------------------------------------------------

class TestWALConcurrency:
    def test_two_threads_different_jobs_complete_within_200ms(self):
        """Two threads calling update_progress on different jobs finish ≤200ms.

        Uses a real file-based SQLite DB so WAL mode is active; each thread
        operates on a distinct job_id — no lock contention inside the repo.
        """
        conn, db_path = _make_file_db()
        try:
            repo = _make_repo(conn)
            jid_a = "jobConcurA001"
            jid_b = "jobConcurB001"
            repo.create(jid_a, VIDEO_ID)
            repo.create(jid_b, "abcdefghijk")

            errors: list = []
            barrier = threading.Barrier(2)

            def run(job_id, value):
                try:
                    barrier.wait()
                    repo.update_progress(job_id, value)
                except Exception as e:
                    errors.append(e)

            start = time.monotonic()
            t1 = threading.Thread(target=run, args=(jid_a, 30))
            t2 = threading.Thread(target=run, args=(jid_b, 50))
            t1.start(); t2.start()
            t1.join(timeout=0.5); t2.join(timeout=0.5)
            elapsed = time.monotonic() - start

            assert not errors, f"Thread errors: {errors}"
            assert elapsed < 0.2, f"Took {elapsed:.3f}s > 200ms"
        finally:
            conn.close()
            db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Progress monotonicity multi-thread (strict mode)
# ---------------------------------------------------------------------------

class TestProgressMonotonicityMultiThread:
    def test_max_value_wins_under_concurrent_updates(self, db_conn):
        """Two threads interleave update_progress; stored value = max attempted.

        Thread A writes 40, thread B writes 70.
        In strict mode (autouse), the lower-arriving thread raises AssertionError
        if it reads the other's higher value first — that's acceptable.
        The invariant: final stored progress == 70 (highest written).
        """
        repo = _make_repo(db_conn)
        jid = "jobMonoTest01"
        repo.create(jid, VIDEO_ID)

        barrier = threading.Barrier(2)
        errors: list = []

        def thread_a():
            try:
                barrier.wait()
                repo.update_progress(jid, 40)
            except AssertionError:
                pass  # acceptable in strict mode
            except Exception as e:
                errors.append(("a", e))

        def thread_b():
            try:
                barrier.wait()
                repo.update_progress(jid, 70)
            except AssertionError:
                pass  # acceptable in strict mode
            except Exception as e:
                errors.append(("b", e))

        t1 = threading.Thread(target=thread_a)
        t2 = threading.Thread(target=thread_b)
        t1.start(); t2.start()
        t1.join(timeout=1.0); t2.join(timeout=1.0)

        assert not errors, f"Unexpected errors: {errors}"
        final = repo.get(jid)["progress"]
        assert final == 70, f"Expected 70, got {final}"

    def test_max_value_wins_production_mode(self, db_conn, monkeypatch):
        """Production mode (no EL_TEST_STRICT): lower writes are silent no-ops.

        No exceptions expected; the highest value must persist.
        """
        monkeypatch.delenv("EL_TEST_STRICT", raising=False)
        repo = _make_repo(db_conn)
        jid = "jobMonoProd01"
        repo.create(jid, VIDEO_ID)

        barrier = threading.Barrier(2)
        errors: list = []

        def writer(value):
            try:
                barrier.wait()
                repo.update_progress(jid, value)
            except Exception as e:
                errors.append((value, e))

        t1 = threading.Thread(target=writer, args=(30,))
        t2 = threading.Thread(target=writer, args=(80,))
        t1.start(); t2.start()
        t1.join(timeout=1.0); t2.join(timeout=1.0)

        assert not errors, f"Errors in production mode: {errors}"
        final = repo.get(jid)["progress"]
        assert final == 80, f"Expected 80, got {final}"


# ---------------------------------------------------------------------------
# T02 M1: Cross-instance monotonicity (two distinct JobsRepo instances)
# ---------------------------------------------------------------------------

class TestCrossInstanceMonotonicity:
    def test_two_distinct_instances_max_wins(self, db_conn, monkeypatch):
        """Two *different* JobsRepo instances sharing the same connection cannot
        lower progress — the highest attempted value must win.

        This is the T02 M1 regression: a per-instance threading.Lock cannot
        protect against races between separate instances.  The fix uses a
        SQL-level conditional UPDATE (WHERE progress <= ?) so atomicity is
        delegated to SQLite.
        """
        monkeypatch.delenv("EL_TEST_STRICT", raising=False)
        repo_a = _make_repo(db_conn)
        repo_b = _make_repo(db_conn)  # distinct instance, same conn
        jid = "jobCrossInst01"
        repo_a.create(jid, VIDEO_ID)

        barrier = threading.Barrier(2)
        errors: list = []

        def writer_a():
            try:
                barrier.wait()
                repo_a.update_progress(jid, 30)
            except Exception as e:
                errors.append(("a", e))

        def writer_b():
            try:
                barrier.wait()
                repo_b.update_progress(jid, 80)
            except Exception as e:
                errors.append(("b", e))

        t1 = threading.Thread(target=writer_a)
        t2 = threading.Thread(target=writer_b)
        t1.start(); t2.start()
        t1.join(timeout=1.0); t2.join(timeout=1.0)

        assert not errors, f"Cross-instance errors: {errors}"
        final = repo_a.get(jid)["progress"]
        assert final == 80, f"Expected 80 (max attempted), got {final}"
