"""SQLite connection factory for EchoLearn.

Applies WAL journal mode and foreign key enforcement on every connection.
This is the only legitimate code path for opening a SQLite connection in
the application; routers, services, and repositories all go through here.
"""

import sqlite3
from pathlib import Path
from typing import Optional

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "echolearn.db"


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a sqlite3.Connection with WAL mode and foreign keys enabled.

    Args:
        db_path: Override the default DB path. Pass ":memory:" for in-memory
                 connections (tests). Defaults to data/echolearn.db.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    path = db_path if db_path is not None else str(_DB_PATH)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn
