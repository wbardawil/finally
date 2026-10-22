"""Tests for ticker, side, and quantity validation."""

from decimal import Decimal

import pytest

from app.errors import AppError
from app.validation import normalize_side, normalize_ticker, parse_quantity


class TestTicker:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("AAPL", "AAPL"),
            ("aapl", "AAPL"),
            ("  msft \n", "MSFT"),
            ("V", "V"),
            ("GOOGL", "GOOGL"),
            ("brk.b", "BRK.B"),
        ],
    )
    def test_valid(self, raw, expected):
        assert normalize_ticker(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", ".", "...", "TOOLONG", "AB1", "BRK.", ".B", "BRK.BB", "A-B", "AA PL", None, 123],
    )
    def test_invalid(self, raw):
        with pytest.raises(AppError) as exc:
            normalize_ticker(raw)
        assert exc.value.status_code == 400


class TestSide:
    @pytest.mark.parametrize("raw,expected", [("buy", "buy"), ("SELL", "sell"), (" Buy ", "buy")])
    def test_valid(self, raw, expected):
        assert normalize_side(raw) == expected

    @pytest.mark.parametrize("raw", ["", "hold", "short", None, 1])
    def test_invalid(self, raw):
        with pytest.raises(AppError):
            normalize_side(raw)


class TestQuantity:
    @pytest.mark.parametrize(
        "raw,expected",
        [(1, "1"), (10, "10"), (0.5, "0.5"), (0.1, "0.1"), (1.2345, "1.2345"), (0.0001, "0.0001")],
    )
    def test_valid(self, raw, expected):
        assert parse_quantity(raw) == Decimal(expected)

    @pytest.mark.parametrize(
        "raw",
        [0, -1, -0.5, 0.0, 1.23456, 0.00001, float("nan"), float("inf"), "10", None, True, [1]],
    )
    def test_invalid(self, raw):
        with pytest.raises(AppError):
            parse_quantity(raw)
