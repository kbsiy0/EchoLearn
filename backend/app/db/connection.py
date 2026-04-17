"""SQLite connection factory for EchoLearn.

Applies WAL journal mode and foreign key enforcement on every connection.
This is the only legitimate code path for opening a SQLite connection in
the application; routers, services, and repositories all go through here.
"""

import sqlite3
from pathlib import Path
from typing import Optional

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
# C1 fix: three .parent hops → backend/app/db → backend/app → backend
# Then append data/echolearn.db to land at backend/data/echolearn.db
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "echolearn.db"

_SCHEMA_SQL = _SCHEMA_PATH.read_text()


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a sqlite3.Connection with WAL mode and foreign keys enabled.

    On each call the schema is applied via executescript so that the
    database file and all tables are created if they do not yet exist.
    Because the schema uses IF NOT EXISTS, repeated calls are safe and cheap.

    Args:
        db_path: Override the default DB path. Pass ":memory:" for in-memory
                 connections (tests). Defaults to data/echolearn.db.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    # C1 fix: ensure the parent directory exists (fresh clone has no data/)
    resolved = Path(db_path) if db_path is not None else _DB_PATH
    if str(resolved) != ":memory:":
        resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    # C2 fix: apply schema on every connection; IF NOT EXISTS makes this safe
    conn.executescript(_SCHEMA_SQL)
    return conn
