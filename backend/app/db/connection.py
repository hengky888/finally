"""SQLite connection handling.

Connections are cheap: open one per unit of work and close it. A single
connection is not safe to share across threads.

Accessors never commit. Wrap a unit of work in `with conn:` and sqlite3
commits it on success, rolls it back on an exception.
"""

import sqlite3

DEFAULT_DB_PATH = "db/finally.db"

_db_path = DEFAULT_DB_PATH


def set_db_path(path: str) -> None:
    """Point subsequent connections at path."""
    global _db_path
    _db_path = str(path)


def get_db_path() -> str:
    """Path the next connection will open."""
    return _db_path


def get_connection() -> sqlite3.Connection:
    """Open a connection to the configured database, rows as sqlite3.Row.

    isolation_level="" keeps implicit transactions on, so `with conn:` is a
    real commit/rollback boundary rather than a no-op.
    """
    conn = sqlite3.connect(_db_path, isolation_level="")
    conn.row_factory = sqlite3.Row
    return conn
