"""Schema definition, initialization and default seed data."""

import sqlite3
from pathlib import Path

from app.market.seed_prices import SEED_PRICES

from .common import DEFAULT_USER_ID, new_id, now_iso
from .connection import DEFAULT_DB_PATH, get_connection, set_db_path

DEFAULT_CASH_BALANCE = 10000.0

# The market module owns the ticker universe; it has to have prices for them.
DEFAULT_TICKERS = list(SEED_PRICES)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    id TEXT PRIMARY KEY DEFAULT 'default',
    cash_balance REAL NOT NULL DEFAULT 10000.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    total_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    actions TEXT,
    created_at TEXT NOT NULL
);
"""


def init_db(path: str = DEFAULT_DB_PATH) -> None:
    """Create the schema at path and seed defaults if the database is fresh.

    Idempotent: re-running against an existing database changes nothing.
    Subsequent get_connection() calls use this path.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    set_db_path(path)
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA)
        _seed(conn)
    conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """Insert the default profile and watchlist into a fresh database.

    An empty user_profile marks a brand-new database. Keying off that one
    marker means a user who clears their watchlist keeps it cleared.
    """
    if conn.execute("SELECT 1 FROM user_profile LIMIT 1").fetchone():
        return
    conn.execute(
        "INSERT INTO user_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now_iso()),
    )
    conn.executemany(
        "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        [(new_id(), DEFAULT_USER_ID, ticker, now_iso()) for ticker in DEFAULT_TICKERS],
    )
