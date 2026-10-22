"""API tests: status codes, response shapes, {"error": ...} bodies."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(db_path, cache):
    with TestClient(create_app(price_cache=cache, db_path=db_path)) as c:
        yield c


def _trade(client, **body):
    return client.post("/api/portfolio/trade", json=body)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_startup_creates_seeded_db(client, db_path):
    assert db_path.exists()
    assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0


def test_trade_success_shape(client):
    r = _trade(client, ticker="aapl", quantity=10, side="buy")
    assert r.status_code == 200
    assert r.json() == {
        "ticker": "AAPL",
        "side": "buy",
        "quantity": 10.0,
        "price": 190.0,
        "notional": 1900.0,
        "cash_balance": 8100.0,
    }


def test_buy_then_portfolio_and_history(client, cache):
    _trade(client, ticker="AAPL", quantity=10, side="buy")
    cache.update("AAPL", 200.0)
    p = client.get("/api/portfolio").json()
    assert p["cash_balance"] == 8100.0
    assert p["total_value"] == 10100.0
    assert p["positions"][0]["unrealized_pnl"] == 100.0
    h = client.get("/api/portfolio/history").json()
    assert [s["total_value"] for s in h["snapshots"]] == [10000.0]


@pytest.mark.parametrize(
    "body,message",
    [
        ({"ticker": "AAPL1", "quantity": 1, "side": "buy"}, "Invalid ticker"),
        ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "greater than 0"),
        ({"ticker": "AAPL", "quantity": -1, "side": "buy"}, "greater than 0"),
        ({"ticker": "AAPL", "quantity": 1.00001, "side": "buy"}, "4 decimal"),
        ({"ticker": "AAPL", "quantity": "1", "side": "buy"}, "must be a number"),
        ({"ticker": "AAPL", "quantity": 1, "side": "short"}, "Side must be"),
        ({"ticker": "AAPL", "quantity": 1000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "Insufficient shares"),
        ({"ticker": "MSFT", "quantity": 1, "side": "buy"}, "No price available"),
    ],
)
def test_trade_validation_errors_are_400(client, body, message):
    r = _trade(client, **body)
    assert r.status_code == 400
    assert set(r.json()) == {"error"}
    assert message in r.json()["error"]


def test_missing_fields_are_400_with_error_body(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL"})
    assert r.status_code == 400
    assert "quantity" in r.json()["error"] and "side" in r.json()["error"]


def test_malformed_json_is_400(client):
    r = client.post(
        "/api/portfolio/trade", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    assert "error" in r.json()


def test_unknown_route_uses_error_shape(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": "Not Found"}


def test_failed_trade_leaves_state_unchanged(client):
    _trade(client, ticker="AAPL", quantity=1000, side="buy")
    p = client.get("/api/portfolio").json()
    assert p["cash_balance"] == 10000.0 and p["positions"] == []
    assert client.get("/api/portfolio/history").json()["snapshots"] == []


def test_snapshot_loop_records_periodically(db_path, cache):
    import time

    with TestClient(create_app(price_cache=cache, db_path=db_path, snapshot_interval=0.05)) as c:
        deadline = time.time() + 2
        while time.time() < deadline and not c.get("/api/portfolio/history").json()["snapshots"]:
            time.sleep(0.05)
        assert c.get("/api/portfolio/history").json()["snapshots"][0]["total_value"] == 10000.0
