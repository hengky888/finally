"""Fixtures for database tests."""

import pytest

from app.db import get_connection, init_db


@pytest.fixture
def db_path(tmp_path):
    """Path to a freshly initialized database file."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    """Open connection to the initialized test database."""
    connection = get_connection()
    yield connection
    connection.close()
