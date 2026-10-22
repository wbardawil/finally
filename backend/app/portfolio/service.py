"""Portfolio logic: trade execution, valuation, snapshots.

Money rules (PLAN.md Section 7):
- notional = quantity x price, rounded half-up to cents, must be >= $0.01
- that one notional drives the cash check, the cash update, and the response
- cash_balance is always stored rounded to cents
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.db import DEFAULT_USER_ID, new_id, now_iso, transaction
from app.errors import AppError
from app.market import PriceCache
from app.validation import normalize_side, normalize_ticker, parse_quantity

CENT = Decimal("0.01")
QTY_STEP = Decimal("0.0001")
HISTORY_LIMIT = 500


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TradeResult:
    ticker: str
    side: str
    quantity: float
    price: float
    notional: float
    cash_balance: float

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "notional": self.notional,
            "cash_balance": self.cash_balance,
        }


def execute_trade(
    conn: sqlite3.Connection,
    cache: PriceCache,
    ticker: object,
    side: object,
    quantity: object,
) -> TradeResult:
    """Validate and execute a market order at the current cached price.

    Raises AppError (400) on bad input, missing price, insufficient cash or shares.
    The check and all writes run in one BEGIN IMMEDIATE transaction, so concurrent
    manual and LLM trades cannot both pass a balance check against stale state.
    """
    ticker = normalize_ticker(ticker)
    side = normalize_side(side)
    qty = parse_quantity(quantity)

    raw_price = cache.get_price(ticker)
    if raw_price is None:
        raise AppError(f"No price available for {ticker}")
    price = _dec(raw_price)

    notional = _cents(qty * price)
    if notional < CENT:
        raise AppError("Trade value must be at least $0.01")

    with transaction(conn):
        cash = _dec(_get_cash(conn))
        position = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE ticker = ?", (ticker,)
        ).fetchone()
        held = _dec(position["quantity"]) if position else Decimal(0)
        ts = now_iso()

        if side == "buy":
            if notional > cash:
                raise AppError(f"Insufficient cash: need ${notional}, have ${_cents(cash)}")
            new_cash = _cents(cash - notional)
            new_qty = (held + qty).quantize(QTY_STEP)
            # Cost basis tracks cash actually paid (the rounded notional).
            old_basis = held * _dec(position["avg_cost"]) if position else Decimal(0)
            avg_cost = (old_basis + notional) / new_qty
            if position:
                conn.execute(
                    "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? WHERE ticker = ?",
                    (float(new_qty), float(avg_cost), ts, ticker),
                )
            else:
                conn.execute(
                    "INSERT INTO positions (id, ticker, quantity, avg_cost, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_id(), ticker, float(new_qty), float(avg_cost), ts),
                )
        else:
            if qty > held:
                raise AppError(f"Insufficient shares: trying to sell {qty} {ticker}, hold {held}")
            new_cash = _cents(cash + notional)
            new_qty = (held - qty).quantize(QTY_STEP)
            if new_qty == 0:
                conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
            else:
                # avg_cost is unchanged on partial sells.
                conn.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? WHERE ticker = ?",
                    (float(new_qty), ts, ticker),
                )

        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (float(new_cash), DEFAULT_USER_ID),
        )
        conn.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), ticker, side, float(qty), float(price), ts),
        )
        _insert_snapshot(conn, cache)

    return TradeResult(
        ticker=ticker,
        side=side,
        quantity=float(qty),
        price=float(price),
        notional=float(notional),
        cash_balance=float(new_cash),
    )


def _get_cash(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id = ?", (DEFAULT_USER_ID,)
    ).fetchone()
    if row is None:  # pragma: no cover - init_db always seeds the user
        raise AppError("User profile missing", status_code=500)
    return row["cash_balance"]


def get_portfolio(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    """Cash, positions valued at cached prices, total value, unrealized P&L.

    A position with no cached price (e.g. right after startup) reports
    current_price/unrealized_pnl/pnl_percent as null and is valued at cost
    basis in total_value, so the total never silently drops the holding.
    """
    cash = _get_cash(conn)
    rows = conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions ORDER BY ticker"
    ).fetchall()

    positions = []
    positions_value = Decimal(0)
    total_pnl = Decimal(0)
    for row in rows:
        qty = _dec(row["quantity"])
        avg_cost = _dec(row["avg_cost"])
        cost_basis = qty * avg_cost
        raw_price = cache.get_price(row["ticker"])
        if raw_price is None:
            market_value = cost_basis
            pnl = None
            pnl_percent = None
        else:
            market_value = qty * _dec(raw_price)
            pnl = market_value - cost_basis
            total_pnl += pnl
            # "% change" is versus average cost (PLAN.md 13 B16).
            pnl_percent = (_dec(raw_price) - avg_cost) / avg_cost * 100 if avg_cost else Decimal(0)
        positions_value += market_value
        positions.append(
            {
                "ticker": row["ticker"],
                "quantity": row["quantity"],
                "avg_cost": float(_cents(avg_cost)),
                "current_price": raw_price,
                "market_value": float(_cents(market_value)),
                "unrealized_pnl": None if pnl is None else float(_cents(pnl)),
                "pnl_percent": None if pnl_percent is None else float(_cents(pnl_percent)),
            }
        )

    return {
        "cash_balance": cash,
        "positions_value": float(_cents(positions_value)),
        "total_value": float(_cents(_dec(cash) + positions_value)),
        "unrealized_pnl": float(_cents(total_pnl)),
        "positions": positions,
    }


def _insert_snapshot(conn: sqlite3.Connection, cache: PriceCache) -> float:
    total = get_portfolio(conn, cache)["total_value"]
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, total_value, recorded_at) VALUES (?, ?, ?)",
        (new_id(), total, now_iso()),
    )
    return total


def record_snapshot(conn: sqlite3.Connection, cache: PriceCache) -> float:
    """Record the current total portfolio value. Returns the recorded value."""
    with transaction(conn):
        return _insert_snapshot(conn, cache)


def get_history(conn: sqlite3.Connection, limit: int = HISTORY_LIMIT) -> list[dict]:
    """The most recent `limit` snapshots, oldest first (ready to plot)."""
    rows = conn.execute(
        "SELECT total_value, recorded_at FROM portfolio_snapshots "
        "ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"total_value": r["total_value"], "recorded_at": r["recorded_at"]} for r in reversed(rows)]
