"""
pytest configuration for EchoLearn backend tests.

- Provides an in-memory SQLite fixture (db_conn) with the full schema applied.
- Sets EL_TEST_STRICT=1 so update_progress raises AssertionError on regression
  rather than logging WARN and no-op'ing (production behaviour).
- No network, no filesystem DB, no real FFmpeg/Whisper/translation in any test
  that uses these fixtures.

Schema location: loaded from app/db/schema.sql (deterministic DDL, chosen over
inlining because future tasks can also reference the file directly).
"""

import os
import sqlite3
from pathlib import Path

import pytest

# Locate the schema file relative to this conftest
_SCHEMA_PATH = Path(__file__).parent.parent / "app" / "db" / "schema.sql"


def _apply_schema(conn: sqlite3.Connection) -> None:
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)
    conn.commit()


@pytest.fixture(autouse=True)
def el_test_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force EL_TEST_STRICT=1 for every test so progress regressions are loud."""
    monkeypatch.setenv("EL_TEST_STRICT", "1")


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """In-memory SQLite connection with the full EchoLearn schema applied.

    WAL mode is skipped for in-memory DBs (not supported); the schema DDL uses
    CREATE TABLE IF NOT EXISTS so re-entrant fixture use is safe.
    Returns a live connection; caller must not close it — the fixture owns lifecycle.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_schema(conn)
    yield conn
    conn.close()
