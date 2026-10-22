"""Tests for lazy DB init, schema, and seeding."""

from app.db import DEFAULT_WATCHLIST, get_connection, init_db

TABLES = {
    "users_profile",
    "watchlist",
    "positions",
    "trades",
    "portfolio_snapshots",
    "chat_messages",
}


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


class TestInit:
    def test_creates_file_and_parent_dir(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "finally.db"
        with get_connection(path):
            pass
        assert path.exists()

    def test_creates_all_tables(self, conn):
        assert TABLES <= _tables(conn)

    def test_no_user_id_outside_users_profile(self, conn):
        for table in TABLES - {"users_profile"}:
            assert "user_id" not in _columns(conn, table), table

    def test_schema_columns(self, conn):
        assert _columns(conn, "users_profile") == {"id", "cash_balance", "created_at"}
        assert _columns(conn, "watchlist") == {"id", "ticker", "added_at"}
        assert _columns(conn, "positions") == {"id", "ticker", "quantity", "avg_cost", "updated_at"}
        assert _columns(conn, "trades") == {
            "id", "ticker", "side", "quantity", "price", "executed_at"
        }
        assert _columns(conn, "portfolio_snapshots") == {"id", "total_value", "recorded_at"}
        assert _columns(conn, "chat_messages") == {
            "id", "role", "content", "actions", "created_at"
        }

    def test_seeds_default_user(self, conn):
        rows = conn.execute("SELECT id, cash_balance FROM users_profile").fetchall()
        assert [(r["id"], r["cash_balance"]) for r in rows] == [("default", 10000.0)]

    def test_seeds_default_watchlist(self, conn):
        tickers = {r["ticker"] for r in conn.execute("SELECT ticker FROM watchlist")}
        assert tickers == set(DEFAULT_WATCHLIST)
        assert len(DEFAULT_WATCHLIST) == 10

    def test_init_is_idempotent(self, db_path):
        init_db(db_path)
        init_db(db_path)
        with get_connection(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 10

    def test_emptied_watchlist_is_not_reseeded(self, db_path):
        init_db(db_path)
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM watchlist")
        init_db(db_path)
        with get_connection(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0

    def test_existing_cash_is_preserved(self, db_path):
        init_db(db_path)
        with get_connection(db_path) as conn:
            conn.execute("UPDATE users_profile SET cash_balance = 42.5")
        init_db(db_path)
        with get_connection(db_path) as conn:
            assert conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0] == 42.5

    def test_missing_tables_are_created_in_existing_file(self, db_path):
        init_db(db_path)
        with get_connection(db_path) as conn:
            conn.execute("DROP TABLE trades")
        init_db(db_path)
        with get_connection(db_path) as conn:
            assert "trades" in _tables(conn)

    def test_deleted_file_is_recreated_lazily(self, db_path):
        with get_connection(db_path):
            pass
        db_path.unlink()
        with get_connection(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 10

    def test_db_path_env_var(self, tmp_path, monkeypatch):
        from app.db import default_db_path

        monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
        assert default_db_path() == tmp_path / "x.db"
