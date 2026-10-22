"""Input validation shared by manual endpoints and (later) LLM actions."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from .errors import AppError

TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
MAX_QUANTITY_DECIMALS = 4


def normalize_ticker(raw: object) -> str:
    """Strip + uppercase, then validate against ^[A-Z]{1,5}(\\.[A-Z])?$."""
    if not isinstance(raw, str):
        raise AppError("Invalid ticker")
    ticker = raw.strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise AppError(f"Invalid ticker: {raw!r}")
    return ticker


def normalize_side(raw: object) -> str:
    side = raw.strip().lower() if isinstance(raw, str) else None
    if side not in ("buy", "sell"):
        raise AppError("Side must be 'buy' or 'sell'")
    return side


def parse_quantity(raw: object) -> Decimal:
    """Quantity must be a finite JSON number > 0 with at most 4 decimal places.

    Returned as Decimal (via str(), so 0.1 stays exactly 0.1) for exact money math.
    """
    # bool is an int subclass; strings are rejected rather than coerced.
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise AppError("Quantity must be a number")
    if isinstance(raw, float) and not math.isfinite(raw):
        raise AppError("Quantity must be a finite number")
    try:
        qty = Decimal(str(raw))
    except InvalidOperation:  # pragma: no cover - finite numbers always parse
        raise AppError("Quantity must be a number") from None
    if qty <= 0:
        raise AppError("Quantity must be greater than 0")
    if -qty.normalize().as_tuple().exponent > MAX_QUANTITY_DECIMALS:
        raise AppError(f"Quantity must have at most {MAX_QUANTITY_DECIMALS} decimal places")
    return qty
