"""Tests for trade execution, valuation, and snapshots."""

import threading

import pytest

from app.db import get_connection
from app.errors import AppError
from app.portfolio import execute_trade, get_history, get_portfolio, record_snapshot


def _cash(conn):
    return conn.execute("SELECT cash_balance FROM users_profile").fetchone()[0]


def _position(conn, ticker):
    return conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestBuy:
    def test_buy_debits_cash_and_opens_position(self, conn, cache):
        r = execute_trade(conn, cache, "AAPL", "buy", 10)
        assert r.to_dict() == {
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 10.0,
            "price": 190.0,
            "notional": 1900.0,
            "cash_balance": 8100.0,
        }
        assert _cash(conn) == 8100.0
        pos = _position(conn, "AAPL")
        assert pos["quantity"] == 10
        assert pos["avg_cost"] == 190.0

    def test_normalizes_ticker_and_side(self, conn, cache):
        r = execute_trade(conn, cache, " aapl ", "BUY", 1)
        assert (r.ticker, r.side) == ("AAPL", "buy")

    def test_second_buy_weights_avg_cost(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)  # 10 @ 190
        cache.update("AAPL", 210.0)
        execute_trade(conn, cache, "AAPL", "buy", 30)  # 30 @ 210
        pos = _position(conn, "AAPL")
        assert pos["quantity"] == 40
        assert pos["avg_cost"] == pytest.approx(205.0)

    def test_insufficient_cash_rejected_and_nothing_written(self, conn, cache):
        with pytest.raises(AppError, match="Insufficient cash"):
            execute_trade(conn, cache, "AAPL", "buy", 100)  # $19,000 > $10,000
        assert _cash(conn) == 10000.0
        assert _position(conn, "AAPL") is None
        assert _count(conn, "trades") == 0
        assert _count(conn, "portfolio_snapshots") == 0

    def test_buy_exactly_all_cash(self, conn, cache):
        cache.update("AAPL", 100.0)
        r = execute_trade(conn, cache, "AAPL", "buy", 100)
        assert r.cash_balance == 0.0

    def test_one_cent_over_is_rejected(self, conn, cache):
        cache.update("AAPL", 100.0)
        conn.execute("UPDATE users_profile SET cash_balance = 9999.99")
        with pytest.raises(AppError, match="Insufficient cash"):
            execute_trade(conn, cache, "AAPL", "buy", 100)


class TestSell:
    def test_partial_sell_credits_cash_and_keeps_avg_cost(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)
        cache.update("AAPL", 200.0)
        r = execute_trade(conn, cache, "AAPL", "sell", 4)
        assert r.notional == 800.0
        assert r.cash_balance == 8900.0
        pos = _position(conn, "AAPL")
        assert pos["quantity"] == 6
        assert pos["avg_cost"] == 190.0

    def test_sell_at_a_loss(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)  # cash 8100
        cache.update("AAPL", 150.0)
        r = execute_trade(conn, cache, "AAPL", "sell", 10)
        assert r.cash_balance == 9600.0  # lost $400

    def test_sell_to_zero_deletes_position(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)
        execute_trade(conn, cache, "AAPL", "sell", 10)
        assert _position(conn, "AAPL") is None
        assert _cash(conn) == 10000.0

    def test_fractional_lots_sell_to_exact_zero(self, conn, cache):
        # 0.1 + 0.1 + 0.1 != 0.3 in floats; must still close the position.
        for _ in range(3):
            execute_trade(conn, cache, "AAPL", "buy", 0.1)
        execute_trade(conn, cache, "AAPL", "sell", 0.3)
        assert _position(conn, "AAPL") is None

    def test_sell_more_than_owned_rejected(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 5)
        with pytest.raises(AppError, match="Insufficient shares"):
            execute_trade(conn, cache, "AAPL", "sell", 5.0001)
        assert _position(conn, "AAPL")["quantity"] == 5
        assert _count(conn, "trades") == 1

    def test_sell_unheld_ticker_rejected(self, conn, cache):
        with pytest.raises(AppError, match="Insufficient shares"):
            execute_trade(conn, cache, "TSLA", "sell", 1)


class TestMoneyRules:
    def test_notional_rounds_half_up_to_cents(self, conn, cache):
        # 0.5 x 2.01 = 1.005 exactly, but float math gives 1.00499... -> round() = 1.0.
        cache.update("AAPL", 2.01)
        r = execute_trade(conn, cache, "AAPL", "buy", 0.5)
        assert r.notional == 1.01
        assert r.cash_balance == 9998.99

    def test_half_cent_notional_rounds_up_to_minimum(self, conn, cache):
        cache.update("PENNY", 0.05)
        r = execute_trade(conn, cache, "PENNY", "buy", 0.1)  # $0.005 -> $0.01
        assert r.notional == 0.01

    def test_notional_below_one_cent_rejected(self, conn, cache):
        cache.update("PENNY", 0.04)
        with pytest.raises(AppError, match="at least \\$0.01"):
            execute_trade(conn, cache, "PENNY", "buy", 0.1)  # $0.004 -> $0.00

    def test_cash_always_stored_in_cents(self, conn, cache):
        cache.update("AAPL", 190.37)
        execute_trade(conn, cache, "AAPL", "buy", 0.3333)  # 63.450321 -> 63.45
        assert _cash(conn) == 9936.55

    def test_avg_cost_tracks_rounded_notional(self, conn, cache):
        cache.update("AAPL", 190.37)
        r = execute_trade(conn, cache, "AAPL", "buy", 0.3333)
        pos = _position(conn, "AAPL")
        assert pos["quantity"] * pos["avg_cost"] == pytest.approx(r.notional)

    def test_too_many_decimals_rejected(self, conn, cache):
        with pytest.raises(AppError, match="4 decimal"):
            execute_trade(conn, cache, "AAPL", "buy", 1.00001)

    def test_no_price_rejected(self, conn, cache):
        with pytest.raises(AppError, match="No price available for MSFT"):
            execute_trade(conn, cache, "MSFT", "buy", 1)

    def test_invalid_ticker_rejected_before_price_lookup(self, conn, cache):
        with pytest.raises(AppError, match="Invalid ticker"):
            execute_trade(conn, cache, "AAPL1", "buy", 1)


class TestRecords:
    def test_trade_appended_to_log(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 2)
        execute_trade(conn, cache, "AAPL", "sell", 1)
        rows = conn.execute("SELECT ticker, side, quantity, price FROM trades").fetchall()
        assert sorted(tuple(r) for r in rows) == [("AAPL", "buy", 2, 190.0), ("AAPL", "sell", 1, 190.0)]

    def test_snapshot_recorded_after_each_trade(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)
        cache.update("AAPL", 200.0)
        execute_trade(conn, cache, "TSLA", "buy", 1)
        assert [s["total_value"] for s in get_history(conn)] == [10000.0, 10100.0]


class TestConcurrency:
    def test_parallel_buys_never_overdraw(self, db_path, cache):
        # Each buy costs $1,900; $10,000 affords exactly 5 of 20 attempts.
        with get_connection(db_path):
            pass
        results, errors = [], []

        def buy():
            with get_connection(db_path) as c:
                try:
                    results.append(execute_trade(c, cache, "AAPL", "buy", 10))
                except AppError as e:
                    errors.append(e)

        threads = [threading.Thread(target=buy) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5 and len(errors) == 15
        with get_connection(db_path) as c:
            assert _cash(c) == 500.0
            assert _position(c, "AAPL")["quantity"] == 50
            assert _count(c, "trades") == 5


class TestValuation:
    def test_empty_portfolio(self, conn, cache):
        assert get_portfolio(conn, cache) == {
            "cash_balance": 10000.0,
            "positions_value": 0.0,
            "total_value": 10000.0,
            "unrealized_pnl": 0.0,
            "positions": [],
        }

    def test_values_positions_at_live_price(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)  # cost 1900
        cache.update("AAPL", 209.0)
        p = get_portfolio(conn, cache)
        assert p["total_value"] == 8100.0 + 2090.0
        assert p["unrealized_pnl"] == 190.0
        assert p["positions"] == [
            {
                "ticker": "AAPL",
                "quantity": 10.0,
                "avg_cost": 190.0,
                "current_price": 209.0,
                "market_value": 2090.0,
                "unrealized_pnl": 190.0,
                "pnl_percent": 10.0,
            }
        ]

    def test_missing_price_valued_at_cost(self, conn, cache):
        execute_trade(conn, cache, "AAPL", "buy", 10)
        cache.remove("AAPL")
        p = get_portfolio(conn, cache)
        assert p["total_value"] == 10000.0
        pos = p["positions"][0]
        assert pos["current_price"] is None
        assert pos["unrealized_pnl"] is None and pos["pnl_percent"] is None


class TestHistory:
    def test_history_is_capped_and_oldest_first(self, conn, cache):
        for i in range(5):
            conn.execute("UPDATE users_profile SET cash_balance = ?", (1000.0 + i,))
            record_snapshot(conn, cache)
        hist = get_history(conn, limit=3)
        assert [h["total_value"] for h in hist] == [1002.0, 1003.0, 1004.0]

    def test_default_cap_is_500(self, conn, cache):
        conn.executemany(
            "INSERT INTO portfolio_snapshots (id, total_value, recorded_at) VALUES (?, ?, ?)",
            [(str(i), float(i), f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00") for i in range(600)],
        )
        hist = get_history(conn)
        assert len(hist) == 500
        assert hist[0]["total_value"] == 100.0 and hist[-1]["total_value"] == 599.0
