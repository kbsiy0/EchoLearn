"""SQLite connection factory for EchoLearn.

Applies schema + WAL mode once per DB path (cached); per-connection PRAGMAs
(foreign_keys) still run on every call. The cache preserves the existing
first-call-bootstraps contract for tests while eliminating the per-request
executescript cost on the hot path.

This is the only legitimate code path for opening a SQLite connection;
routers, services, and repositories all go through here.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "echolearn.db"

_SCHEMA_SQL = _SCHEMA_PATH.read_text()

_initialized_paths: set[str] = set()
_init_lock = threading.Lock()


def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a sqlite3.Connection with WAL mode and foreign keys enabled.

    Schema + WAL PRAGMA run once per DB path (cached via _initialized_paths).
    ":memory:" always re-bootstraps because each connection is a separate DB.

    Args:
        db_path: Override the default DB path. Pass ":memory:" for in-memory
                 connections (tests). Defaults to data/echolearn.db.
    """
    resolved = Path(db_path) if db_path is not None else _DB_PATH
    resolved_str = str(resolved)
    is_memory = resolved_str == ":memory:"

    if not is_memory:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(resolved_str, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    if is_memory:
        _bootstrap(conn)
        return conn

    with _init_lock:
        if resolved_str not in _initialized_paths:
            _bootstrap(conn)
            _initialized_paths.add(resolved_str)

    return conn
