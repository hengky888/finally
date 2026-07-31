"""SQLite persistence layer for FinAlly.

Public API:
    init_db(path)   - create the schema and seed defaults; idempotent
    get_connection() - open a connection with dict-style rows

    Per-table accessor modules: profile, watchlist, positions, trades,
    snapshots, chat. They return dicts and keep user_id internal.

Accessors never commit. Wrap a unit of work that must be all-or-nothing in
`with conn:`, which sqlite3 commits on success and rolls back on an exception.
"""

from . import chat, positions, profile, snapshots, trades, watchlist
from .connection import get_connection
from .schema import init_db

__all__ = [
    "init_db",
    "get_connection",
    "profile",
    "watchlist",
    "positions",
    "trades",
    "snapshots",
    "chat",
]
