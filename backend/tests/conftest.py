"""Pytest configuration and fixtures.

Event loop setup is handled by pytest-asyncio via `asyncio_mode = "auto"` and
`asyncio_default_fixture_loop_scope` in pyproject.toml; no fixture overrides
are needed here.
"""
