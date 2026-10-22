"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def event_loop_policy():
    """Use the default event loop policy for all async tests."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def db_path(tmp_path):
    """Path to a fresh, not-yet-created SQLite file."""
    return tmp_path / "test.db"


@pytest.fixture
def cache():
    from app.market import PriceCache

    c = PriceCache()
    c.update("AAPL", 190.0)
    c.update("TSLA", 250.0)
    return c


@pytest.fixture
def conn(db_path):
    from app.db import get_connection

    with get_connection(db_path) as c:
        yield c
