"""SQLite connection management with lazy schema creation and seeding."""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

DEFAULT_USER_ID = "default"
DEFAULT_CASH = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# backend/app/db/connection.py -> repo root is three levels above app/
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "db" / "finally.db"

_initialized: set[str] = set()
_init_lock = Lock()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def default_db_path() -> Path:
    """DB file location: DB_PATH env var, else <repo>/db/finally.db (local runs)."""
    env = os.environ.get("DB_PATH", "").strip()
    return Path(env) if env else _DEFAULT_DB_PATH


def _open(db_path: Path) -> sqlite3.Connection:
    # isolation_level=None: autocommit; transactions are explicit (BEGIN IMMEDIATE).
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create tables if missing and seed defaults on a fresh database.

    Seeding is keyed on the default user row: if it is absent the DB is new,
    so the user and the default watchlist are inserted together. An existing
    user whose watchlist was emptied on purpose is left alone.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(db_path)
    try:
        conn.executescript(_SCHEMA_PATH.read_text())
        conn.execute("BEGIN IMMEDIATE")
        try:
            exists = conn.execute(
                "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER_ID,)
            ).fetchone()
            if not exists:
                ts = now_iso()
                conn.execute(
                    "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                    (DEFAULT_USER_ID, DEFAULT_CASH, ts),
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO watchlist (id, ticker, added_at) VALUES (?, ?, ?)",
                    [(new_id(), t, ts) for t in DEFAULT_WATCHLIST],
                )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def ensure_initialized(db_path: Path) -> None:
    """Run init_db once per process per path (lazy init on first use).

    If the file is deleted while the process runs, it is recreated and reseeded.
    """
    key = str(db_path.resolve())
    if key in _initialized and db_path.exists():
        return
    with _init_lock:
        if key in _initialized and db_path.exists():
            return
        init_db(db_path)
        _initialized.add(key)


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection to an initialized database; closes on exit."""
    path = db_path or default_db_path()
    ensure_initialized(path)
    conn = _open(path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception.

    IMMEDIATE takes the write lock up front, so a check-then-update sequence
    (e.g. cash balance check + debit) cannot interleave with another writer.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
