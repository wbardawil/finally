"""SQLite persistence: schema, lazy init, seed data, connections.

Public API:
    get_connection   - Context manager yielding a connection to an initialized DB
    transaction      - BEGIN IMMEDIATE / COMMIT / ROLLBACK context manager
    init_db          - Create schema and seed defaults (idempotent)
    default_db_path  - DB_PATH env var or <repo>/db/finally.db
"""

from .connection import (
    DEFAULT_CASH,
    DEFAULT_USER_ID,
    DEFAULT_WATCHLIST,
    default_db_path,
    get_connection,
    init_db,
    new_id,
    now_iso,
    transaction,
)

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_USER_ID",
    "DEFAULT_WATCHLIST",
    "default_db_path",
    "get_connection",
    "init_db",
    "new_id",
    "now_iso",
    "transaction",
]
